from libs import Helper
import logging


class Schedule(object):

    def __init__(self, name: str, intervals: list, period: int, time_shift: int):
        self.truncation_mask = 0b11111111111111111111000000000000
        self.name = name
        self.intervals = intervals
        self.period = period
        self.time_shift = time_shift  # Not used

        self.shifted_intervals = None
        self.truncated_schedule = None

    def shift_schedule(self):
        """
        Shifts a schedule by an offset. The schedule will be shifted to the left.
        This function is not used anymore!
        """

        schedule = self.intervals

        if self.time_shift == 0:
            return schedule

        # Last higher interval border is the duration
        duration = schedule[-1]["high"]

        new_s = []
        for s in schedule:
            l = (s["low"] - self.time_shift) % duration
            h = (s["high"] - self.time_shift) % duration
            if l >= h:
                # Overflow, interval needs to be split
                l_1 = 0
                h_1 = h
                l_2 = l
                h_2 = duration
                new_s.append({'low': l_1, 'high': h_1,
                             'state': s['state'], 'ipv': s['ipv']})
                new_s.append({'low': l_2, 'high': h_2,
                             'state': s['state'], 'ipv': s['ipv']})
            else:
                new_s.append(
                    {'low': l, 'high': h, 'state': s['state'], 'ipv': s['ipv']})

        new_s = sorted(new_s, key=lambda i: i['low'])
        return new_s

    def truncate_schedule(self, intervals):
        """
        Truncate the time slices (intervals) of this schedule to 20 bit.
        """

        schedule = []

        for idx, d in enumerate(intervals):

            # As the range match type is inclusive on both interval borders,
            # we shift the upper border by -1
            # We do not need to shift if there is only a single interval or if it is the last one
            interval_border = 0 if idx == len(intervals) - 1 else 1

            # Apply 20 Bit mask to interval border.
            # Fill to 48 Bit and shift 12 bit to have only the valid 20 bit, rest will be 0
            s = {"low": int(bin(d["low"] & self.truncation_mask)[2:].zfill(48), 2) >> 12,
                 "high": (int(bin(d["high"] & self.truncation_mask)[2:].zfill(48), 2) - interval_border) >> 12,
                 "state": d["state"], "ipv": d["ipv"], "octets": d["octets"]}

            schedule.append(s)

        return schedule

    def create_schedule(self):
        """
        Create the stream GCL
        """
        #self.shifted_intervals = self.shift_schedule()
        self.truncated_schedule = self.truncate_schedule(
            self.intervals)

        return self.truncated_schedule


class StreamGateInstance(object):

    def __init__(self, gate_id: int, ipv: int,
                 schedule: Schedule,
                 gate_closed_due_to_invalid_rx_enable: bool,
                 gate_closed_due_to_octets_exceeded_enable: bool):

        try:
            assert (ipv <= 8 and ipv > 0)
        except AssertionError:
            logging.error(
                "IPV can only be a value from 0-8, schedule not created.")

        self.gate_id = gate_id
        self.ipv = ipv
        self.schedule = schedule
        self.gate_closed_due_to_invalid_rx_enable = gate_closed_due_to_invalid_rx_enable
        self.gate_closed_due_to_octets_exceeded_enable = gate_closed_due_to_octets_exceeded_enable
        self.schedule_written = False


class FlowMeterInstance(object):

    def __init__(self, flow_meter_id: int,
                 cir_kbps: int, pir_kbps: int,
                 cbs: int, pbs: int,
                 dropOnYellow: bool, markAllFramesRedEnable: bool,
                 colorAware: bool):

        try:
            assert pir_kbps > cir_kbps
            assert pbs > cbs
        except AssertionError:
            logging.error(
                "Misconfigured token bucket rates! Ensure that PIR > CIR and PBS > CBS. Ignoring this rule.")

        self.flow_meter_id = flow_meter_id
        self.cir_kbps = cir_kbps
        self.pir_kbps = pir_kbps
        self.cbs = cbs
        self.pbs = pbs
        self.dropOnYellow = dropOnYellow
        self.markAllFramesRedEnable = markAllFramesRedEnable
        self.colorAware = colorAware


class StreamFilterInstance(object):

    def __init__(self, stream_handle: int, stream_gate: StreamGateInstance, max_sdu: int, pcp,
                 flow_meter: FlowMeterInstance):

        self.stream_handle = stream_handle
        self.stream_gate = stream_gate
        self.max_sdu = max_sdu + 7  # Adding recirculation header size on top
        self.pcp = pcp
        self.flow_meter = flow_meter


class StreamID:
    def __init__(self, vid: int, stream_handle: int, eth_dst: str = None,
                 eth_src: str = None, ipv4_src: str = None, ipv4_dst: str = None,
                 ipv4_diffserv: int = None, ipv4_prot: int = None, src_port: int = None,
                 dst_port: int = None, active: bool = False, overwrite_eth_dst: str = None,
                 overwrite_vid: int = None, overwrite_pcp=None,
                 stream_block_enable=False):
        """
        Creates either a tuple for an exact match, or a tuple for a wildcard match to to combine all stream identification functions into one.
        Third parameter 't' in tuple is used to indicate that a ternary match will be done.
        """

        self.vid = vid
        self.eth_dst = (eth_dst, Helper.str_to_mac(
            "ff:ff:ff:ff:ff:ff"), "t") if eth_dst else (0, 0, "t")
        self.eth_src = (eth_src, Helper.str_to_mac(
            "ff:ff:ff:ff:ff:ff"), "t") if eth_src else (0, 0, "t")
        self.ipv4_src = (ipv4_src, "255.255.255.255",
                         "t") if ipv4_src else ("0.0.0.0", "0", "t")
        self.ipv4_dst = (ipv4_dst, "255.255.255.255",
                         "t") if ipv4_dst else ("0.0.0.0", "0", "t")
        self.ipv4_diffserv = (ipv4_diffserv, ipv4_diffserv,
                              "t") if ipv4_diffserv else (0, 0, "t")
        self.ipv4_prot = (ipv4_prot, ipv4_prot,
                          "t") if ipv4_prot else (0, 0, "t")
        self.src_port = (src_port, src_port, "t") if src_port else (0, 0, "t")
        self.dst_port = (dst_port, dst_port, "t") if dst_port else (0, 0, "t")
        self.stream_handle = stream_handle
        self.stream_block_enable = stream_block_enable

        if active:
            # Active stream identification. Needed to determine if IPV should be overwritten.
            self.active = True

            self.overwrite_eth_dst = overwrite_eth_dst if overwrite_eth_dst else eth_dst
            self.overwrite_vid = overwrite_vid if overwrite_vid else vid
            try:
                self.overwrite_pcp = overwrite_pcp
            except ValueError:
                raise ValueError(
                    "overwrite_pcp field is mandatory if active is set to true!")
        else:
            self.active = active
