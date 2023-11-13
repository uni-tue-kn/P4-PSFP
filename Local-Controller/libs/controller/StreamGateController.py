import bfrt_grpc.client as gc
import logging

from libs.configuration import Config
from libs.Switch import Switch
from typing import List
from libs.instances.instances import StreamGateInstance


class StreamGateController(object):

    def __init__(self, switch: Switch, gates: List[StreamGateInstance], config: Config):
        self.s = switch
        self.gates = gates
        self.config = config

        self.s.reset_register(
            register_name="ingress.psfp_c.streamGate_c.reg_gate_blocked")

        # Each interval has a unique identifier to filter for the OctetsExceeded parameter.
        self.interval_count = 0

    def write_schedule(self, app_id):
        """
        Creates one table entry per interval from created schedule associated with its gate state.
        An IPV value of 8 indicates that the frame's PCP will be kept!
        """

        pkt_gen_obj = self.s.pkt_gen.app_id_mapping[app_id]
        port = pkt_gen_obj["port"]

        for m in self.config.schedule_port_mappings:
            if m["port"] == port:
                schedule_name = m["schedule"]
                break

        if not schedule_name:
            logging.critical(f"Schedule {app_id=} on {port=} not found in config!")
            return

        for g in self.gates:
            # Only write schedules that fit to this configured port
            if g.schedule.name == schedule_name:
                if not g.schedule_written:
                    intervals = g.schedule.create_schedule()

                    for s in intervals:
                        try:
                            self.interval_count += 1
                            self.s.write_table_entry(table="ingress.psfp_c.streamGate_c.stream_gate_instance",
                                            match_fields={"ig_md.stream_filter.stream_gate_id": g.gate_id,
                                                            "hdr.recirc_time.match_ts": (s["low"], s["high"], "r")},
                                            action_name="ingress.psfp_c.streamGate_c.set_gate_and_ipv",
                                            action_params={"gate_state": s["state"],
                                                            "ipv": s["ipv"],
                                                            "interval_identifier": self.interval_count,
                                                            "max_octects_interval": s["octets"]}
                                            )
                        except gc.BfruntimeReadWriteRpcException:
                            logging.warn(
                                f"Schedule for {g.gate_id=} already exists!")
                        
                    g.schedule_written = True

    def eval_write_schedules(self, first_period_ts):
        # Only used for evaluation!
        resolution = 10

        for g in self.gates:
            if g.gate_id == 4:
                waiting = int(bin(800000000 & 0b11111111111111111111000000000000)[
                              2:].zfill(48), 2) >> 12

                first_period_ts = int(bin(first_period_ts & 0b11111111111111111111000000000000)[
                                      2:].zfill(48), 2) >> 12

                start = first_period_ts  # + waiting

                intervals = [(start + i * resolution, start + (i+1)
                              * resolution - 1) for i in range(1000)]

                for l, h in intervals:
                    for c in [0, 1, 2, 3]:
                        try:
                            self.s.write_table_entry(table="ingress.psfp_c.flowMeter_c.evaluation_p4tg",
                                              match_fields={"hdr.recirc_time.orig_ts": (l, h, "r"),
                                                            "ig_tm_md.packet_color": c},
                                              action_name="ingress.psfp_c.flowMeter_c.count_interval",
                                              action_params={}
                                              )
                        except Exception as e:
                            pass

                # Schedule eval
                """
                for l, h in intervals:
                        try:
                            self.s.write_table_entry(table="ingress.psfp_c.streamGate_c.evaluation_p4tg",
                            match_fields= {"hdr.recirc_time.orig_ts": (l, h, "r")},
                            action_name="ingress.psfp_c.streamGate_c.count_interval",
                            action_params={}
                            )
                        except Exception as e:
                            pass
                """
