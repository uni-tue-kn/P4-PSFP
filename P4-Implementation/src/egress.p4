control egress(
        inout header_t hdr,
        inout egress_metadata_t eg_md,
        in egress_intrinsic_metadata_t eg_intr_md,
        in egress_intrinsic_metadata_from_parser_t eg_intr_from_prsr,
        inout egress_intrinsic_metadata_for_deparser_t eg_intr_md_for_dprsr,
        inout egress_intrinsic_metadata_for_output_port_t eg_intr_md_for_oport) {

        DirectCounter<bit<32>>(CounterType_t.PACKETS) debug_counter1;
        DirectCounter<bit<32>>(CounterType_t.PACKETS) debug_counter2;
        DirectCounter<bit<32>>(CounterType_t.PACKETS) debug_counter3;


        /*
        Select 20 bits from timestamp to match intervals on
        Bit 12 to bit 31 allows for a resolution of
        4μs to 2.1s
        */
        action truncate1(){
            hdr.recirc_time.match_ts[16:0] = hdr.bridge.diff_ts[28:12];
        }
        action truncate2() {
            hdr.recirc_time.match_ts[19:17] = hdr.bridge.diff_ts[31:29];
        }

        // Underflow handling
        action calculate_underflow_timestamp(){
            hdr.bridge.diff_ts = eg_md.difference_max_to_hyperperiod + hdr.bridge.ingress_timestamp;
        }

        // Underflow handling
        action add_rel_ts_and_offset(bit<64> offset, bit<64> hyperperiod_duration){
            eg_md.rel_ts_plus_offset = hdr.bridge.diff_ts + offset;
            eg_md.hyperperiod_duration = hyperperiod_duration;
        }

        // Underflow handling
        action assign_offset_hp_duration(bit<64> offset, bit<64> hyperperiod_duration_offset){
            eg_md.offset = offset;
            // This time, the control plane pre calculated hyperperiod - offset and stores the value here
            eg_md.hyperperiod_minus_offset = hyperperiod_duration_offset;
            debug_counter1.count();
        }

        // Underflow handling
        action calc_uf_shift_left(){
            // Action to calculate if we got an underflow by subtracting the offset

            // Value to be matched on, new rel_pos
            eg_md.new_rel_pos_with_offset = hdr.bridge.diff_ts - eg_md.offset;
            // Set new_pos = hyperperiod - offset + rel. Will be overwritten if no under flow happens
            hdr.bridge.diff_ts = eg_md.hyperperiod_minus_offset + hdr.bridge.diff_ts;
        }

        // Underflow handling
        action set_pos_shift_left(){
            hdr.bridge.diff_ts = eg_md.new_rel_pos_with_offset;
            debug_counter2.count();
        }

        // Underflow handling
        action reset_diff_ts(){
            hdr.bridge.diff_ts = 0;
        }

        action nop(){}

        /*
        This table detects an underflow of the relative position in hyperperiod.
        It has a very large value if an underflow happened.
        This table performs a maximum comparison operation by applying a ternary mask
        e.g. mask:1111111100000000000000 result:0
        if it has a result > 0 (i.e. a table miss), it means that the value was very large
        */
        table underflow_detection {
            key = {
                hdr.bridge.diff_ts: ternary;
            }
            actions = {
                nop;
                reset_diff_ts;
            }
            size = 8;
        }


        table map_offset_shift_right {
            key = {
                hdr.bridge.ingress_port: exact;
            }
            actions = {
                add_rel_ts_and_offset;
            }
            default_action = add_rel_ts_and_offset(0, 99999999999999);
            size = 16;
        }

        table offset_detection_shift_right {
            key = {
                eg_md.new_rel_pos_with_offset: ternary;
            }
            actions = {
                nop;
            }
            size = 8;
        }

        table map_offset_shift_left {
            key = {
                hdr.bridge.ingress_port: exact;
            }
            actions = {
                assign_offset_hp_duration;
            }
            default_action = assign_offset_hp_duration(0, 99999999999999);
            size = 16;
            counters = debug_counter1;
        }

        table offset_detection_shift_left {
            key = {
                eg_md.new_rel_pos_with_offset: ternary;
            }
            actions = {
                set_pos_shift_left;
            }
            size = 8;
            counters = debug_counter2;
        }

        table decide_shift_dir {
            key = {
                hdr.bridge.ingress_port: exact;
            }
            actions = {
                nop;
            }
            default_action = nop;
            size = 8;
        }

    apply {
        // Packet is destined to be recirculated
        if (hdr.bridge.isValid()){
            // Add the packet length as header and recirculate
            hdr.recirc.setValid();

            hdr.recirc.pkt_len = eg_intr_md.pkt_length;
            hdr.recirc.period_count = hdr.bridge.period_count;

            hdr.recirc_time.setValid();


            if (underflow_detection.apply().miss){
                // We have an underflow by subtracting ingress ts from hyperperiod ts
                eg_md.difference_max_to_hyperperiod = MAXIMUM_48_BIT_TS - (bit<64>)hdr.bridge.hyperperiod_ts;
                calculate_underflow_timestamp();
            }

            if (decide_shift_dir.apply().hit){
                // Offset is positive, timestamps will be shifted right
                map_offset_shift_right.apply();
                
                /*
                Calculate new relative position for later use
                */
                eg_md.new_rel_pos_with_offset = eg_md.rel_ts_plus_offset - eg_md.hyperperiod_duration;

                /*
                Match on new_rel_pos_with_offset. Check rel + offset > hyperperiod?
                If the table misses, we did not jump over a finished hyperperiod and can simply use
                    Set new_pos = rel + offset
                */
                if (offset_detection_shift_right.apply().miss) {
                    hdr.bridge.diff_ts = eg_md.rel_ts_plus_offset;
                }
                else {
                    /*
                    If we get a match in the table, we jumped over a finished hyperperiod and need to subtract a full hyperperiod of it
                        Set new_pos = rel + offset - hyperperiod
                    */
                    hdr.bridge.diff_ts = eg_md.new_rel_pos_with_offset;
                }
            } else {
                // Offset is interpreted negative, timestamps will be shifted left
                if (map_offset_shift_left.apply().hit) {
                    /*
                    Set value to new_pos for underflow handling
                        Set new_pos = hyperperiod - offset + rel
                    */
                    calc_uf_shift_left();

                    /*
                    If hit: No underflow, just subtract offset
                        Set new_pos = rel - offset
                    */
                    offset_detection_shift_left.apply();
                }

            }
            // Truncate and add the relative timestamp in hyperperiod to recirculation header
            truncate1();
            truncate2();

            hdr.bridge.setInvalid();
        }


        /*
        ! P4TG evaluation specific
        */
        if (eg_intr_md.egress_port == 188 || eg_intr_md.egress_port == 40 ) {
            hdr.ethernet.ether_type = ether_type_t.IPV4;
            hdr.eth_802_1q.setInvalid();

            //hdr.ipv4.dstAddr = 0x0A0B0C0D;

            if (hdr.ipv4.srcAddr != 0x01020304){
                eg_intr_md_for_dprsr.drop_ctl = 1;
            }

        }    
    }
}
