import logging
import bfrt_grpc.client as gc
from scapy.all import Ether

class PktGen():
    def __init__(self, switch):
        self.s = switch
        self.pipe_ids = [0, 1]
        self.pipe_ports = [68, 196]
        self.configured = False
        self.p = self.build_pkt()
        # Mapping from app_id to internal port number.
        # This allows us to have up to 8 different hyperperiod schedules (one per port)

        self.app_id_mapping = {}
        for a in range(8):
            # Initialize app_id structure
            self.app_id_mapping[a] = {"pkt_count": None,              # Will be filled later
                                      "interval_length": None,
                                      "port": None,                 # Port where PSFP with this schedule will be applied
                                      "hyperperiod_done": False,    # Indicates if first hyperperiod is done
                                      "Delta": {"epsilon_1": 0, "epsilon_2": 0, "delta": 0, "sum": 0},
                                      "hyperperiod_register_value": 0,
                                      "hyperperiod_duration": None}

    def reset_registers(self):
        self.s.reset_register(register_name="ingress.psfp_c.lower_last_ts")
        self.s.reset_register(register_name="ingress.psfp_c.higher_last_ts")
        self.s.reset_register(register_name="ingress.psfp_c.pkt_count")
        self.s.reset_register(register_name="ingress.psfp_c.hyperperiod_done")
        self.s.reset_register(register_name="ingress.psfp_c.period_count")
        logging.info(f"Reset period counter registers on Switch {self.s.name}")

    def build_pkt(self):
        """
        Mocking packet to sent.
        """
        pktlen = 100
        p = Ether(src="00:06:07:08:09:0a",
                  dst='ff:ff:ff:ff:ff:ff', type=0xBB02)
        p = p / ("0" * (pktlen - len(p)))
        return p

    def set_up_pkt_gen(self):
        """
        Reset all registers and configure pkt generator.
        """
        self.reset_registers()
        if not self.configured:
            self.enable_pktgen()
        return

    def configure_app_id_to_port(self, app_id):
        """
        Creates a table entry in the assign_app_id_port table matching for this instance app_id and port.
        """
        app = self.app_id_mapping[app_id]

        port = app["port"]
        self.s.write_table_entry(table="ingress.psfp_c.app_id_port",
                          match_fields={"hdr.timer.app_id": app_id},
                          action_name="ingress.psfp_c.assign_app_id_port",
                          action_params={"port": port}
                          )
        logging.debug(f"app_id {app_id} to port {port} configured.")

    def configure_timer_table(self, app_id):
        """
        Creates table entries to identify the generated packets.

        :param app_id: int of this schedule.
        """
        for idx, i in enumerate(self.pipe_ids):
            self.s.write_table_entry(table="ingress.psfp_c.timed_pkt",
                              match_fields={"hdr.timer.pipe_id": i,
                                            "hdr.timer.app_id": app_id,
                                            "hdr.timer.batch_id": 0,
                                            "hdr.timer.packet_id": 0,
                                            "ig_intr_md.ingress_port": self.pipe_ports[idx]},
                              action_name="ingress.psfp_c.set_pkt_count",
                              action_params={
                                  "pkt_count_hyperperiod": self.app_id_mapping[app_id]['pkt_count']}
                              )
        logging.debug("Timer Table configured.")

    def enable_pktgen(self):
        """
        Globally enable packet generation on this switch and write entries for buffering the packet.
        """
        pktgen_port_cfg_table = self.s.bfrt_info.table_get("port_cfg")
        pktgen_pkt_buffer_table = self.s.bfrt_info.table_get("pkt_buffer")

        # Enable packet generation on the ports
        for p in self.pipe_ports:
            logging.info(f"Enabling pktgen on port {p}...")
            pktgen_port_cfg_table.entry_add(
                self.s.target,
                [pktgen_port_cfg_table.make_key([gc.KeyTuple('dev_port', p)])],
                [pktgen_port_cfg_table.make_data([gc.DataTuple('pktgen_enable', bool_val=True)])])

        logging.info("Configuring packet buffer...")
        pktgen_pkt_buffer_table.entry_add(
            self.s.target,
            [pktgen_pkt_buffer_table.make_key([gc.KeyTuple('pkt_buffer_offset', 144),
                                               gc.KeyTuple('pkt_buffer_size', 94)])],  # ! pktlen - 6
            [pktgen_pkt_buffer_table.make_data([gc.DataTuple('buffer', bytearray(bytes(self.p)[6:]))])])

        self.configured = True

    def calc_period_packets(self, period):
        """
        As the maximum pkt generation interval is 2^32 ~ 4s, we need to generate several packets for
        bigger periods. This function calculates the needed amount of pkts and the interval.
        I.e. a period of 10s results in a pkt count of 4 with an interval duration of 2.5s

        :param period: int of the period

        :returns pkt_count, interval_length:
        """

        max_period = 2**32

        if period < max_period:
            return 1, period

        for pkt_count in range(3, 100):
            interval_length = int(period / pkt_count)
            if (period % pkt_count == 0 and interval_length < max_period):
                return pkt_count, interval_length
        raise ValueError("Period requires more than 100 packets. Adjust?")

    def configure_pkt_gen(self, app_id, period, port):
        """
        Configure a new periodic schedule and create entries to match on generated packets.

        :param app_id: Schedule identifier, 0-7
        :param period: Period of the schedule in ns
        :param port: Port where this period should be configured
        """

        try:
            assert app_id >= 0 and app_id <= 7
        except AssertionError:
            logging.critical(
                "App_id {app_id} is not valid! Only values from 0 to 7 are allowed.")
            return

        pktgen_app_cfg_table = self.s.bfrt_info.table_get("app_cfg")
        self.app_id_mapping[app_id]["pkt_count"], self.app_id_mapping[app_id]["interval_length"] = self.calc_period_packets(
            period)
        self.app_id_mapping[app_id]["hyperperiod_duration"] = self.app_id_mapping[app_id]['pkt_count'] * \
            self.app_id_mapping[app_id]['interval_length']
        self.app_id_mapping[app_id]["port"] = port

        # Configure the packet generation timer application
        data = pktgen_app_cfg_table.make_data([gc.DataTuple('timer_nanosec', self.app_id_mapping[app_id]["interval_length"]),
                                               gc.DataTuple(
                                                   'app_enable', bool_val=False),
                                               # pktlen - 6
                                               gc.DataTuple('pkt_len', 94),
                                               gc.DataTuple(
                                                   'pkt_buffer_offset', 144),
                                               gc.DataTuple(
                                                   'pipe_local_source_port', self.pipe_ports[0]),
                                               gc.DataTuple(
                                                   'increment_source_port', bool_val=False),
                                               gc.DataTuple(
                                                   'batch_count_cfg', 0),
                                               gc.DataTuple(
                                                   'packets_per_batch_cfg', 0),
                                               gc.DataTuple('ibg', 1),
                                               gc.DataTuple('ibg_jitter', 0),
                                               gc.DataTuple('ipg', 1000),
                                               gc.DataTuple('ipg_jitter', 500),
                                               gc.DataTuple(
                                                   'batch_counter', 0),
                                               gc.DataTuple('pkt_counter', 0),
                                               gc.DataTuple('trigger_counter', 0)],
                                              'trigger_timer_periodic')
        pktgen_app_cfg_table.entry_mod(
            self.s.target,
            [pktgen_app_cfg_table.make_key([gc.KeyTuple('app_id', app_id)])],
            [data])

        logging.info("Enabling pktgen...")
        pktgen_app_cfg_table.entry_mod(
            self.s.target,
            [pktgen_app_cfg_table.make_key([gc.KeyTuple('app_id', app_id)])],
            [pktgen_app_cfg_table.make_data([gc.DataTuple('app_enable', bool_val=True)],
                                            'trigger_timer_periodic')]
        )

        self.configure_timer_table(app_id)
        self.configure_app_id_to_port(app_id)

    def disable_pkt_gen(self):
        """
        Disable the packet generator by setting the app_enable parameter to False
        in the pktgen config table
        """

        logging.info("Disabling pktgen...")
        pktgen_app_cfg_table = self.s.bfrt_info.table_get("app_cfg")

        for app_id in self.app_id_mapping.keys():
            pktgen_app_cfg_table.entry_mod(
                self.s.target,
                [pktgen_app_cfg_table.make_key(
                    [gc.KeyTuple('app_id', app_id)])],
                [pktgen_app_cfg_table.make_data([gc.DataTuple('app_enable', bool_val=False)],
                                                'trigger_timer_periodic')]
            )

    def get_pkt_gen_config(self):
        """
        This function prints the switch table entries of the configured packet generators for all configured app_ids.

        """
        pktgen_app_cfg_table = self.s.bfrt_info.table_get("app_cfg")

        for a in self.app_id_mapping.keys():
            resp = pktgen_app_cfg_table.entry_get(
                self.s.target,
                [pktgen_app_cfg_table.make_key([gc.KeyTuple('app_id', a)])],
                {"from_hw": True}
            )
            data_dict = next(resp)[0].to_dict()
            print(data_dict)

    def init_clock_drift_offset_detection_table(self):
        """
        Clock drift offset tables are initialized here. They contain a very large bitmask
        to mimic a maximum comparison.

        There are several tables to either shift to the left or to the right.
        They are initialized with an offset of 0.
        """

        # Mask to filter for large values (2^38, which is around 4.5 minutes)
        mask_max_underflow = 0b111111111111111000000000000000000000000000000000

        self.s.write_table_entry(table="egress.offset_detection_shift_right",
                          match_fields={"eg_md.new_rel_pos_with_offset": (
                              0, mask_max_underflow, "t")},
                          action_name="egress.nop",
                          action_params={}
                          )

        self.s.write_table_entry(table="egress.offset_detection_shift_left",
                          match_fields={"eg_md.new_rel_pos_with_offset": (
                              0, mask_max_underflow, "t")},
                          action_name="egress.set_pos_shift_left",
                          action_params={}
                          )

        for a, e in self.app_id_mapping.items():
            port = e["port"]
            if port:
                duration = e["hyperperiod_duration"]
                offset = e["Delta"]["delta"]

                self.s.write_table_entry(table="egress.map_offset_shift_right",
                                  match_fields={
                                      "hdr.bridge.ingress_port": port},
                                  action_name="egress.add_rel_ts_and_offset",
                                  action_params={"offset": offset,
                                                 "hyperperiod_duration": duration}
                                  )

                self.s.write_table_entry(table="egress.map_offset_shift_left",
                                  match_fields={
                                      "hdr.bridge.ingress_port": port},
                                  action_name="egress.assign_offset_hp_duration",
                                  action_params={"offset": offset,
                                                 "hyperperiod_duration_offset": duration - offset}
                                  )

                self.s.write_table_entry(table="egress.decide_shift_dir",
                                  match_fields={
                                      "hdr.bridge.ingress_port": port},
                                  action_name="egress.nop",
                                  action_params={}
                                  )

    def read_hyperperiod_register(self, port):
        """
        Reads the values from both 32-bit and 16-bit hyperperiod registers.
        Both values are appended together into one timestamp value

        :param port: The port to get the period register value from

        :returns period: The period register value
        """

        reg = self.s.read_register(
            register_name="ingress.psfp_c.lower_last_ts", register_index=port)
        lower = reg[0].to_dict()['ingress.psfp_c.lower_last_ts.f1'][0]
        reg = self.s.read_register(
            register_name="ingress.psfp_c.higher_last_ts", register_index=port)
        higher = reg[0].to_dict()['ingress.psfp_c.higher_last_ts.f1'][0]
        bitstring = bin(higher)[2:] + bin(lower)[2:].zfill(32)

        return int(bitstring, 2)

    def set_clock_offset(self, port, offset):
        """
        Set a clock offset value for a schedule on a port.
        Frames on this port will be shifted by offset

        :param port: The port to configure
        :param offset: To offset value to apply, positive or negative
        """

        # Get period duration
        for _, d in self.app_id_mapping.items():
            if d["port"] == port:
                hyperperiod_duration = d["hyperperiod_duration"]
                break

        current_shift_state_right = None
        new_shift_state_right = True if offset >= 0 else False

        # Get the current state: shifting left or shifting right by determining if an entry exists in the direction
        # table for this port
        try:
            direction = self.s.get_table_entries(table="egress.decide_shift_dir", match_fields={
                                        "hdr.bridge.ingress_port": port})
            direction = [k.to_dict() for k in list(direction)[0]]
            if len(direction) > 0:
                current_shift_state_right = True
        except gc.BfruntimeReadWriteRpcException:
            current_shift_state_right = False

        # Write the new offset value
        if new_shift_state_right:
            # Shift right
            self.s.update_table_entry(table="egress.map_offset_shift_right",
                               match_fields={"hdr.bridge.ingress_port": port},
                               action_name="egress.add_rel_ts_and_offset",
                               action_params={"offset": offset,
                                              "hyperperiod_duration": hyperperiod_duration}
                               )
        else:
            # Shift left
            offset *= -1
            self.s.update_table_entry(table="egress.map_offset_shift_left",
                               match_fields={"hdr.bridge.ingress_port": port},
                               action_name="egress.assign_offset_hp_duration",
                               action_params={"offset": offset,
                                              "hyperperiod_duration_offset": hyperperiod_duration - offset}
                               )

        if current_shift_state_right != new_shift_state_right:
            # Need to alter the direction
            if new_shift_state_right:
                # Shift right, write entry
                self.s.write_table_entry(table="egress.decide_shift_dir",
                                  match_fields={
                                      "hdr.bridge.ingress_port": port},
                                  action_name="egress.nop",
                                  action_params={}
                                  )
            else:
                # Shift left, delete entry
                self.s.remove_table_entry(table="egress.decide_shift_dir", match_fields={
                                   "hdr.bridge.ingress_port": port})

        logging.debug(f"Clock drift adaption of {offset}ns set on {port=}.")

    def get_epsilon_2_between_periods(self, previous_diff: int, port1: int, port2: int):
        """
        Having the same period on different ports results in a time delta between schedules
        due to the ports being configured one after another.

        This function needs to be called continuously to calculate the difference between schedules
        and set the clock offset accordingly.

        :param previous_diff: previously calculated difference between period registers of 2 ports
        :param port1: Port1 with the same schedule
        :param port2: Port 2 with the same schedule

        :returns epsilon_2: newly calculated difference
        """

        for _, d in self.app_id_mapping.items():
            if d["port"] == port1:
                period1 = d["hyperperiod_duration"]
            if d["port"] == port2:
                period2 = d["hyperperiod_duration"]

        try:
            assert period1 == period2
        except AssertionError:
            logging.warn(
                f"Periods on {port1=}, {port2=} do not match! Clock offset not applied.")
            return 0

        port1_register = self.s.pkt_gen.read_hyperperiod_register(port1)
        port2_register = self.s.pkt_gen.read_hyperperiod_register(port2)
        epsilon_2 = port1_register - port2_register

        if abs(epsilon_2) < 0.5 * period1:
            if epsilon_2 != previous_diff:
                previous_diff = epsilon_2

                for _, d in self.app_id_mapping.items():
                    if d["port"] == port1:
                        # Only one of the ports needs to be adjusted.
                        # Set the epsilon_2 value here to call the clock offset func later on
                        d["Delta"]["epsilon_2"] = epsilon_2
                        break
        return epsilon_2

    def get_epsilon_1_clock_drift(self):
        """
        Read to consecutive values from a hyperperiod register. 
        If the difference between those two is not equal to the hyperperiod,
        we got a clock drift epsilon_1.
        This is performed for each configured port.

        :param previous_register_value: The value that was in the hyperperiod register before calling this function.
        """

        for _, d in self.app_id_mapping.items():
            if d["port"]:
                period = d["hyperperiod_duration"]
                previous_register_value = d["hyperperiod_register_value"]

                # Read new register value
                port_register = self.s.pkt_gen.read_hyperperiod_register(d["port"])
                if previous_register_value == port_register:
                    # No change, keep values
                    return
                epsilon_1 = (port_register - previous_register_value) % period

                if ((port_register - previous_register_value) / period) % 1 < 0.001:
                    # We look at after decimal points to see by how much we overshoot the hyperperiod
                    # A very small result (< 0.001) means that the generated packet arrived slightly later -> -ε
                    # A very large result (> 0.99) means that the generated packet arrived slightly too soon -> +ε
                    epsilon_1 = -epsilon_1

                # Set the epsilon_1 value here to call the clock offset func later on
                d["Delta"]["epsilon_1"] = epsilon_1
                d["hyperperiod_register_value"] = port_register
        
    def set_delta(self):
        """
        This function sets the δ value of this data plane for all configured ports.
        """
        delta = self.s.delta
        for _, d in self.app_id_mapping.items():
            if d["port"]:
                d["Delta"]["delta"] = delta


    def delta_adjustment(self):
        """
        This function applies the ∆-adjustment to all configured ports.
        Values of ε1, ε2 and δ must be calculated in beforehand.
        """
        for _, d in self.app_id_mapping.items():
            if d["port"]:
                previous_Delta = d["Delta"]["sum"]
                Delta = d["Delta"]["epsilon_1"] + d["Delta"]["epsilon_2"] + d["Delta"]["delta"]
                if Delta != previous_Delta:
                    self.set_clock_offset(d["port"], Delta)
                    d["Delta"]["sum"] = Delta


    def eval_p4tg_set_clock_offset(self, port, offset, hyperperiod_duration, start_ts=None):
        current_shift_state_right = None
        new_shift_state_right = True if offset >= 0 else False

        # Get the current state: shifting left or shifting right by determining if an entry exists in the direction
        # table for this port
        try:
            direction = self.s.get_table_entries(table="egress.decide_shift_dir", match_fields={
                                        "hdr.bridge.ingress_port": port})
            direction = [k.to_dict() for k in list(direction)[0]]
            if len(direction) > 0:
                current_shift_state_right = True
        except gc.BfruntimeReadWriteRpcException:
            current_shift_state_right = False

        # Hyperperiod done ts
        waiting = int(bin(3100000 & 0b11111111111111111111000000000000)[
                      2:].zfill(48), 2) >> 12
        duration = int(bin(1600000 & 0b11111111111111111111000000000000)[
                       2:].zfill(48), 2) >> 12
        start_ts = int(bin(start_ts & 0b11111111111111111111000000000000)[
                       2:].zfill(48), 2) >> 12
        start_ts = start_ts + waiting
        end_ts = start_ts + duration - 1

        # Write the new offset value
        if new_shift_state_right:
            # Shift right
            self.s.write_table_entry(table="egress.map_offset_shift_right",
                              match_fields={"hdr.bridge.ingress_port": port,
                                            "hdr.bridge.ingress_timestamp[31:12]": (start_ts, end_ts, "r")},
                              action_name="egress.add_rel_ts_and_offset",
                              action_params={"offset": offset,
                                             "hyperperiod_duration": hyperperiod_duration}
                              )
            self.s.write_table_entry(table="egress.map_offset_shift_right",
                              match_fields={"hdr.bridge.ingress_port": port,
                                            "hdr.bridge.ingress_timestamp[31:12]": (end_ts + 1, 1048575, "r")},
                              action_name="egress.add_rel_ts_and_offset",
                              action_params={"offset": 0,
                                             "hyperperiod_duration": hyperperiod_duration}
                              )
        else:
            # Shift left
            offset *= -1
            self.s.update_table_entry(table="egress.map_offset_shift_left",
                               match_fields={"hdr.bridge.ingress_port": port},
                               action_name="egress.assign_offset_hp_duration",
                               action_params={"offset": offset,
                                              "hyperperiod_duration_offset": hyperperiod_duration - offset}
                               )

        if current_shift_state_right != new_shift_state_right:
            # Need to alter the direction
            if new_shift_state_right:
                # Shift right, write entry
                self.s.write_table_entry(table="egress.decide_shift_dir",
                                  match_fields={
                                      "hdr.bridge.ingress_port": port},
                                  action_name="egress.nop",
                                  action_params={}
                                  )
            else:
                # Shift left, delete entry
                self.s.remove_table_entry(table="egress.decide_shift_dir", match_fields={
                                   "hdr.bridge.ingress_port": port})
