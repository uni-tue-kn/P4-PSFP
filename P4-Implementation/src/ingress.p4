#include "controls/IPv4.p4"

#include "controls/PSFP.p4"


control ingress(
        inout header_t hdr,
        inout ingress_metadata_t ig_md,
        in ingress_intrinsic_metadata_t ig_intr_md,
        in ingress_intrinsic_metadata_from_parser_t ig_prsr_md,
        inout ingress_intrinsic_metadata_for_deparser_t ig_dprsr_md,
        inout ingress_intrinsic_metadata_for_tm_t ig_tm_md) {

    PSFP() psfp_c;

    IPv4() ipv4_c;

    /*
    ! P4TG evaluation specific!
    */
    action push_vlan_header(bit<12> vid){
        hdr.eth_802_1q.setValid();

        hdr.eth_802_1q.pcp = 2;
        hdr.eth_802_1q.dei = 0;
        hdr.eth_802_1q.vid = vid;
        hdr.eth_802_1q.ether_type = ether_type_t.IPV4;
        hdr.ethernet.ether_type = ether_type_t.ETH_802_1Q;
    }

    table push_802_1q_header {
        key = {
            ig_intr_md.ingress_port: exact;
        }
        actions = {
            push_vlan_header;
        }
        size = 8;
    }


    apply {
        /*
        ! P4TG evaluation specific!
        */
        //push_802_1q_header.apply();

        if (hdr.eth_802_1q.isValid() || hdr.timer.isValid()){
            psfp_c.apply(hdr, ig_md, ig_tm_md, ig_intr_md, ig_dprsr_md);
        }

        if (hdr.ipv4.isValid() && !hdr.bridge.isValid()){
            ipv4_c.apply(hdr, ig_md, ig_tm_md, ig_intr_md, ig_dprsr_md);
        }
    }
}
