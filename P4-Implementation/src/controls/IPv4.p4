control IPv4(inout header_t hdr, 
            inout ingress_metadata_t ig_md, 
            inout ingress_intrinsic_metadata_for_tm_t ig_tm_md, 
            in ingress_intrinsic_metadata_t ig_intr_md, 
            inout ingress_intrinsic_metadata_for_deparser_t ig_dprsr_md) {



    DirectCounter<bit<32>>(CounterType_t.PACKETS) debug_counter;
    action ipv4_forward(mac_addr_t eth_dst_addr, PortId_t port) {
        // Set output port from control plane
        ig_tm_md.ucast_egress_port = port;

        // Change layer 2 addresses: Src of switch, dest of target
        hdr.ethernet.src_addr = hdr.ethernet.dst_addr;
		hdr.ethernet.dst_addr = eth_dst_addr;

        // Decrement TTL
        hdr.ipv4.ttl = hdr.ipv4.ttl - 1;
        debug_counter.count();
    }

    table ipv4 {
        key = {
            hdr.ipv4.dstAddr: lpm;
        }
        actions = {
            ipv4_forward;
        }
        size = 1024;
        counters = debug_counter;
    }

    apply {
        if (hdr.ipv4.isValid()){
            ipv4.apply();
        }
    }
}
