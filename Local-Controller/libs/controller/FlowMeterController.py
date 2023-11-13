import logging

from libs.Switch import Switch
from typing import List
from libs.instances.instances import FlowMeterInstance
class FlowMeterController(object):

    def __init__(self, switch: Switch, flow_meters: List[FlowMeterInstance]):
        self.s = switch
        self.flow_meters = flow_meters
        self.FLOW_METER_ADJUST_RECIRCULATION = -11

    def write_meter_table(self):
        """
        Configure flow meter instance and write the configured values for PIR, PBS, CIR and CBS into data plane.
        """

        for f in self.flow_meters:
            # Write flow meter config flags
            self.s.write_table_entry(table="ingress.psfp_c.flowMeter_c.flow_meter_config",
                              match_fields={
                                  "ig_md.stream_filter.flow_meter_instance_id": f.flow_meter_id},
                              action_name="ingress.psfp_c.flowMeter_c.set_flow_meter_config",
                              action_params={"dropOnYellow": f.dropOnYellow,
                                             "markAllFramesRedEnable": f.markAllFramesRedEnable,
                                             "colorAware": f.colorAware}
                              )

            # Write rates
            self.s.write_table_entry(table="ingress.psfp_c.flowMeter_c.flow_meter_instance",
                              match_fields={
                                  "ig_md.stream_filter.flow_meter_instance_id": f.flow_meter_id},
                              action_name=f"ingress.psfp_c.flowMeter_c.set_color_direct",
                              action_params={"$METER_SPEC_CIR_KBPS": f.cir_kbps,
                                             "$METER_SPEC_PIR_KBPS": f.pir_kbps,
                                             "$METER_SPEC_CBS_KBITS": f.cbs,
                                             "$METER_SPEC_PBS_KBITS": f.pbs}
                              )

            # Subtract recirculation header size from flow meter byte count
            meter_table = self.s.bfrt_info.table_get(
                "ingress.psfp_c.flowMeter_c.flow_meter_instance")
            meter_table.attribute_meter_bytecount_adjust_set(
                self.s.target, self.FLOW_METER_ADJUST_RECIRCULATION)
            resp = meter_table.attribute_get(
                self.s.target, "MeterByteCountAdjust")
            for d in resp:
                assert d["byte_count_adjust"] == self.FLOW_METER_ADJUST_RECIRCULATION
            logging.info("FlowMeter Byte count adjusted.")

    def eval_p4tg_meter_config(self, start_ts):
        duration = int(bin(2000000 & 0b11111111111111111111000000000000)[
                       2:].zfill(48), 2) >> 12
        start_ts = int(bin(start_ts & 0b11111111111111111111000000000000)[
                       2:].zfill(48), 2) >> 12
        start_drop_yellow = start_ts + duration

        self.start_red = start_drop_yellow + duration + 1

        try:
            # DropOnYellow
            self.s.write_table_entry(table="ingress.psfp_c.flowMeter_c.flow_meter_config",
                              match_fields={"ig_md.stream_filter.flow_meter_instance_id": 400,
                                            "hdr.recirc_time.orig_ts": (start_drop_yellow, start_drop_yellow + duration, "r")},
                              action_name="ingress.psfp_c.flowMeter_c.set_flow_meter_config",
                              action_params={"dropOnYellow": True,
                                             "markAllFramesRed": False,
                                             "markAllFramesRedEnable": False,
                                             "colorAware": False}
                              )

            # MarkRed
            self.s.write_table_entry(table="ingress.psfp_c.flowMeter_c.flow_meter_config",
                              match_fields={"ig_md.stream_filter.flow_meter_instance_id": 400,
                                            "hdr.recirc_time.orig_ts": (self.start_red, 1048575, "r")},
                              action_name="ingress.psfp_c.flowMeter_c.set_flow_meter_config",
                              action_params={"dropOnYellow": True,
                                             "markAllFramesRed": True,
                                             "markAllFramesRedEnable": True,
                                             "colorAware": False}
                              )
        except:
            pass
