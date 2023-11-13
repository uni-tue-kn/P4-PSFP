from libs import Helper

from libs.Switch import Switch
from typing import List
from libs.instances.instances import StreamFilterInstance, StreamID

class StreamFilterController(object):

    def __init__(self, switch: Switch, streams: List[StreamID], stream_filters: List[StreamFilterInstance]):
        self.s = switch

        self.streams = streams
        self.stream_filters = stream_filters

        self.s.reset_register(
            register_name="ingress.psfp_c.streamFilter_c.reg_filter_blocked")

    def create_table_entries(self):
        """
        Creates entries in the stream identification table, the active overwrite table and
        the stream filter instance table according to the given 'streams' list.
        """
        for e in self.streams:
            # Ternary matches for every field here!
            # Stream identification and mapping to stream handle
            self.s.write_table_entry(table="ingress.psfp_c.streamFilter_c.stream_id",
                              match_fields={"hdr.ethernet.dst_addr": e.eth_dst,
                                            "hdr.eth_802_1q.vid": e.vid,
                                            "hdr.ethernet.src_addr": e.eth_src,
                                            "hdr.ipv4.srcAddr": e.ipv4_src,
                                            "hdr.ipv4.dstAddr": e.ipv4_dst,
                                            "hdr.ipv4.diffserv": e.ipv4_diffserv,
                                            "hdr.ipv4.protocol": e.ipv4_prot,
                                            "hdr.transport.srcPort": e.src_port,
                                            "hdr.transport.dstPort": e.dst_port},
                              action_name="ingress.psfp_c.streamFilter_c.assign_stream_handle",
                              action_params={"stream_handle": e.stream_handle,
                                             "active": e.active,
                                             "stream_blocked_due_to_oversize_frame_enable": e.stream_block_enable,
                                             }
                              )

            if e.active:
                # Field overwrite parameters for active stream identification
                self.s.write_table_entry(table="ingress.psfp_c.streamFilter_c.stream_id_active",
                                  match_fields={
                                      "ig_md.stream_filter.stream_handle": e.stream_handle},
                                  action_name="ingress.psfp_c.streamFilter_c.overwrite_stream_active",
                                  action_params={"eth_dst_addr": Helper.str_to_mac(e.overwrite_eth_dst),
                                                 "vid": e.overwrite_vid,
                                                 "pcp": e.overwrite_pcp}
                                  )

        for f in self.stream_filters:
            priority_or_wildcard = (
                0, 0, "t") if f.pcp == "*" else (f.pcp, f.pcp, "t")

            # Mapping from stream_handle to stream gate and flow meter instance
            self.s.write_table_entry(table="ingress.psfp_c.streamFilter_c.stream_filter_instance",
                              match_fields={
                                  "ig_md.stream_filter.stream_handle": f.stream_handle},
                              action_name="ingress.psfp_c.streamFilter_c.assign_gate_and_meter",
                              action_params={"stream_gate_id": f.stream_gate.gate_id,
                                             "flow_meter_instance_id": f.flow_meter.flow_meter_id,
                                             "gate_closed_due_to_invalid_rx_enable": f.stream_gate.gate_closed_due_to_invalid_rx_enable,
                                             "gate_closed_due_to_octets_exceeded_enable": f.stream_gate.gate_closed_due_to_octets_exceeded_enable}
                              )

            # Max SDU Filter for each stream_handle
            self.s.write_table_entry(table="ingress.psfp_c.streamFilter_c.max_sdu_filter",
                              match_fields={"ig_md.stream_filter.stream_handle": f.stream_handle,
                                            "hdr.recirc.pkt_len": (0, f.max_sdu, "r"),
                                            "hdr.eth_802_1q.pcp": priority_or_wildcard},
                              action_name="ingress.psfp_c.streamFilter_c.none",
                              action_params={}
                              )
