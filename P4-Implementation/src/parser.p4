/*******************************************************************************
 * BAREFOOT NETWORKS CONFIDENTIAL & PROPRIETARY
 *
 * Copyright (c) 2018-2019 Barefoot Networks, Inc.
 * All Rights Reserved.
 *
 * NOTICE: All information contained herein is, and remains the property of
 * Barefoot Networks, Inc. and its suppliers, if any. The intellectual and
 * technical concepts contained herein are proprietary to Barefoot Networks,
 * Inc.
 * and its suppliers and may be covered by U.S. and Foreign Patents, patents in
 * process, and are protected by trade secret or copyright law.
 * Dissemination of this information or reproduction of this material is
 * strictly forbidden unless prior written permission is obtained from
 * Barefoot Networks, Inc.
 *
 * No warranty, explicit or implicit is provided, unless granted under a
 * written agreement with Barefoot Networks, Inc.
 *
 *
 ******************************************************************************/


parser TofinoIngressParser(packet_in pkt,
                            out ingress_intrinsic_metadata_t ig_intr_md) {

    state start {
        pkt.extract(ig_intr_md);
        transition select(ig_intr_md.resubmit_flag) {
            1 : parse_resubmit;
            0 : parse_port_metadata;
        }
    }

    state parse_resubmit {
        // Parse resubmitted packet here. Not needed
        transition accept;
    }

    state parse_port_metadata {
        // Advance: Skip over port metadata if you do not wish to use it
        #if __TARGET_TOFINO__ == 2
                pkt.advance(192);
        #else
                pkt.advance(64);
        #endif
                transition accept;
    }
}

parser TofinoEgressParser(packet_in pkt,
                            out egress_intrinsic_metadata_t eg_intr_md) {

    state start {
        pkt.extract(eg_intr_md);
        transition accept;
    }
}

// ---------------------------------------------------------------------------
// Ingress parser
// ---------------------------------------------------------------------------
parser SwitchIngressParser(
        packet_in pkt,
        out header_t hdr,
        out ingress_metadata_t ig_md,
        out ingress_intrinsic_metadata_t ig_intr_md) {

    TofinoIngressParser() tofino_parser;

    state start {
        tofino_parser.apply(pkt, ig_intr_md);
        transition select(ig_intr_md.ingress_port){
            PACKET_GEN_PORT_PIPE0: parse_pkt_gen;
            PACKET_GEN_PORT_PIPE1: parse_pkt_gen;
            RECIRCULATE_PORT_PIPE0 : parse_recirculation;
            RECIRCULATE_PORT_PIPE0_2 : parse_recirculation;
            RECIRCULATE_PORT_PIPE0_3 : parse_recirculation;
            RECIRCULATE_PORT_PIPE0_4 : parse_recirculation;
            RECIRCULATE_PORT_PIPE2_1: parse_recirculation;
            RECIRCULATE_PORT_PIPE2_2: parse_recirculation;
            default : parse_ethernet;
        }
    }

    state parse_pkt_gen {
        pkt.extract(hdr.timer);
        transition accept;
    }

    state parse_recirculation {
        // Recirculated pkt
        pkt.extract(hdr.recirc);
        pkt.extract(hdr.recirc_time);
        transition parse_ethernet;
    }

    state parse_ethernet {
        pkt.extract(hdr.ethernet);
        transition select(hdr.ethernet.ether_type) {
            ether_type_t.IPV4 : parse_ipv4;
            ether_type_t.ETH_802_1Q : parse_802_1q;
            default : reject;
        }
    }

    state parse_ipv4 {
        pkt.extract(hdr.ipv4);
        transition select(hdr.ipv4.protocol){
            ip_type_t.UDP : parse_transport;
            ip_type_t.TCP : parse_transport;
            default : reject;
        }
    }

    state parse_transport {
        pkt.extract(hdr.transport);
        transition accept;
    }

    state parse_802_1q {
        pkt.extract(hdr.eth_802_1q);
        transition select(hdr.eth_802_1q.ether_type) {
            ether_type_t.IPV4 : parse_ipv4;
            default: reject;
        }
    }

}

// ---------------------------------------------------------------------------
// Ingress Deparser
// ---------------------------------------------------------------------------
control SwitchIngressDeparser(
        packet_out pkt,
        inout header_t hdr,
        in ingress_metadata_t ig_md,
        in ingress_intrinsic_metadata_for_deparser_t ig_dprsr_md,
        in ingress_intrinsic_metadata_t ig_intr_md) {

    Digest<digest_block_t>() digest_block_psfp;
    Digest<digest_debug_pktgen_t>() digest_pktgen;
    Digest<digest_debug_gate_t>() digest_debug_gate;
    Digest<digest_finished_hyperperiod_t>() digest_hyperperiod;

    apply {
             
        if (ig_dprsr_md.digest_type == 1){
            digest_block_psfp.pack({ig_md.stream_filter.stream_handle, 
                                        ig_md.stream_filter.stream_gate_id, 
                                        ig_dprsr_md.drop_ctl, 
                                        ig_md.stream_gate.PSFPGateEnabled, 
                                        ig_md.block_reason, 
                                        ig_md.flow_meter.color,
                                        ig_md.stream_filter.flow_meter_instance_id});
        }

        else if (ig_dprsr_md.digest_type == 3){
            digest_debug_gate.pack({hdr.recirc_time.match_ts, ig_md.stream_filter.stream_gate_id, hdr.bridge.diff_ts, hdr.bridge.ingress_timestamp, hdr.bridge.hyperperiod_ts, ig_intr_md.ingress_port, hdr.recirc.period_count, hdr.recirc.pkt_len});
        }
        else if (ig_dprsr_md.digest_type == 4){
            digest_pktgen.pack({hdr.timer.pipe_id, hdr.timer.app_id, hdr.timer.batch_id, hdr.timer.packet_id, ig_intr_md.ingress_port});
        }
        else if (ig_dprsr_md.digest_type == 6){
            digest_hyperperiod.pack({ig_md.hyperperiod.port, 
                                     hdr.timer.app_id,
                                     hdr.timer.pipe_id,
                                     ig_intr_md.ingress_mac_tstamp,
                                     ig_dprsr_md.digest_type});
        }

        pkt.emit(hdr.timer);
        pkt.emit(hdr.recirc);
        pkt.emit(hdr.bridge);
        pkt.emit(hdr.ethernet);
        pkt.emit(hdr.eth_802_1q);
        pkt.emit(hdr.ipv4);
        pkt.emit(hdr.transport);
    }
}


// ---------------------------------------------------------------------------
// Egress parser
// ---------------------------------------------------------------------------
parser SwitchEgressParser(
        packet_in pkt,
        out header_t hdr,
        out egress_metadata_t eg_md,
        out egress_intrinsic_metadata_t eg_intr_md) {

    TofinoEgressParser() tofino_parser;

    state start {
        tofino_parser.apply(pkt, eg_intr_md);
        transition select(eg_intr_md.egress_port){
            RECIRCULATE_PORT_PIPE0 : parse_recirculation;
            RECIRCULATE_PORT_PIPE0_2 : parse_recirculation;
            RECIRCULATE_PORT_PIPE0_3 : parse_recirculation;
            RECIRCULATE_PORT_PIPE0_4 : parse_recirculation;
            RECIRCULATE_PORT_PIPE2_1: parse_recirculation;
            RECIRCULATE_PORT_PIPE2_2: parse_recirculation;
            default : parse_ethernet;
        }
    }

    state parse_recirculation {
        // Recirculated pkt
        pkt.extract(hdr.bridge);
        transition accept;
    }

    state parse_ethernet {
        pkt.extract(hdr.ethernet);
        transition select(hdr.ethernet.ether_type) {
            ether_type_t.ETH_802_1Q : parse_802_1q;
            ether_type_t.IPV4 : parse_ipv4;
            default : reject;
        }
    }

    state parse_802_1q {
        pkt.extract(hdr.eth_802_1q);
        transition select(hdr.eth_802_1q.ether_type) {
            ether_type_t.IPV4 : parse_ipv4;
            default: reject;
        }
    }

    state parse_ipv4 {
        pkt.extract(hdr.ipv4);
        transition accept;
    }

}

// ---------------------------------------------------------------------------
// Egress Deparser
// ---------------------------------------------------------------------------
control SwitchEgressDeparser(
        packet_out pkt,
        inout header_t hdr,
        in egress_metadata_t eg_md,
        in egress_intrinsic_metadata_for_deparser_t eg_dprsr_md) {
    Checksum() ipv4_checksum;
    apply {
        if (hdr.ipv4.isValid()){
            hdr.ipv4.hdr_checksum = ipv4_checksum.update(
                    {hdr.ipv4.version,
                    hdr.ipv4.ihl,
                    hdr.ipv4.diffserv,
                    hdr.ipv4.ecn,
                    hdr.ipv4.total_len,
                    hdr.ipv4.identification,
                    hdr.ipv4.flags,
                    hdr.ipv4.frag_offset,
                    hdr.ipv4.ttl,
                    hdr.ipv4.protocol,
                    hdr.ipv4.srcAddr,
                    hdr.ipv4.dstAddr});
        }
        pkt.emit(hdr.recirc);
        pkt.emit(hdr.recirc_time);
        pkt.emit(hdr.ethernet);
        pkt.emit(hdr.eth_802_1q);
        pkt.emit(hdr.ipv4);
        pkt.emit(hdr.transport);
    }
}
