control StreamGate(inout header_t hdr, 
            inout ingress_metadata_t ig_md, 
            inout ingress_intrinsic_metadata_for_tm_t ig_tm_md, 
            in ingress_intrinsic_metadata_t ig_intr_md, 
            inout ingress_intrinsic_metadata_for_deparser_t ig_dprsr_md) {


    DirectCounter<bit<32>>(CounterType_t.PACKETS_AND_BYTES) stream_gate_counter;
    Counter<bit<32>, bit<12>>(32, CounterType_t.PACKETS) not_passed_gate_counter;
    Counter<bit<32>, bit<12>>(32, CounterType_t.PACKETS) missed_interval_counter;    
    Register<bit<1>, void>(2048, 0) reg_gate_blocked;
    RegisterAction<bit<1>, bit<12>, void>(reg_gate_blocked) block_gate = {
        void apply(inout bit<1> value){
            value = 1;
        }
    };

    RegisterAction<bit<1>, bit<12>, bit<1>>(reg_gate_blocked) get_gate_state = {
        void apply(inout bit<1> value, out bit<1> read_value){
            read_value = value;
        }
    };

    // This register holds the period_id. The action returns true/false if a new period started.
    // Used for GateClosedDueToOctetsExceeded
    Register<bit<32>, bit<12>>(2048, 0) state_reset_octets;
    RegisterAction<bit<32>, bit<12>, bool>(state_reset_octets) set_reset_octets_flag = {
        void apply(inout bit<32> period_id, out bool read_value){
            if (hdr.recirc.period_count != period_id){
                period_id = hdr.recirc.period_count;
                read_value = true;
            } else {
               read_value = false;
            }
        }
    };

    // This register holds the packet size of the first frame in this period. 
    // It is needed to subtract from the maximum size configured for an interval.
    // Used for GateClosedDueToOctetsExceeded
    Register<bit<32>, bit<12>>(2048, 0) first_sdu_per_interval;
    RegisterAction<bit<32>, bit<12>, void>(first_sdu_per_interval) set_first_sdu = {
        void apply(inout bit<32> first_sdu) {
            // Set the sdu of this packet because it is the first packet after new period starts
            first_sdu = (bit<32>)hdr.recirc.pkt_len;
        }
    };
    // This action returns 0 or 1 to set the drop_ctl field directly.
    // Used for GateClosedDueToOctetsExceeded
    RegisterAction<bit<32>, bit<12>, bit<3>>(first_sdu_per_interval) get_first_sdu = {
        void apply(inout bit<32> first_sdu, out bit<3> read_value){
            // Retrieve the inital sdu size
            if (ig_md.stream_gate.remaining_octets >= first_sdu){
                read_value = 0;
            } else {
                read_value = 1;
            }
        }
    };

    // Used for GateClosedDueToOctetsExceeded
    Register<bit<32>, bit<12>>(2048, 0) octets_per_interval;
    RegisterAction<bit<32>, bit<12>, void>(octets_per_interval) reset_octets = {
        void apply(inout bit<32> remaining_octets) {
            // Reset register value to maximum
            remaining_octets = ig_md.stream_gate.max_octects_interval;
        }
    };

    // Used for GateClosedDueToOctetsExceeded
    RegisterAction<bit<32>, bit<12>, bit<32>>(octets_per_interval) decrement_octets = {
        void apply(inout bit<32> remaining_octets, out bit<32> read_value) {
            if (remaining_octets > (bit<32>)hdr.recirc.pkt_len) {
                // Check if subtraction goes below 0 -> drop, else decrement
                remaining_octets = remaining_octets - (bit<32>) hdr.recirc.pkt_len;
                read_value = remaining_octets;
            } else {
                // Drop
                read_value = 0;
            }
        }
    };


    action set_gate_and_ipv(bit<1> gate_state, bit<4> ipv, bit<12> interval_identifier, bit<32> max_octects_interval) {
                            
        ig_md.stream_gate.PSFPGateEnabled = gate_state;
        ig_md.stream_gate.ipv = ipv;
        ig_md.stream_gate.max_octects_interval = max_octects_interval;
        ig_md.stream_gate.interval_identifier = interval_identifier;

        stream_gate_counter.count();
    }

    // Holds the time intervalls and gate states
    table stream_gate_instance {  
        key = {
            ig_md.stream_filter.stream_gate_id: exact;
            hdr.recirc_time.match_ts: range;
        }
        actions = {
            set_gate_and_ipv;
        }
        counters = stream_gate_counter;
        size = __STREAM_GATE_SIZE__;
    }  

    apply {    
        if (ig_dprsr_md.drop_ctl == 0){
            if (stream_gate_instance.apply().miss){
                // Stream identified, but no stream gate assigned, or no open interval matched. Drop frame.
                ig_dprsr_md.drop_ctl = 1;
                missed_interval_counter.count(ig_md.stream_filter.stream_gate_id);

                //ig_dprsr_md.digest_type = 3;

                if (ig_md.stream_gate.gate_closed_due_to_invalid_rx_enable){
                        // Permanently close the gate
                        block_gate.execute(ig_md.stream_filter.stream_gate_id);
                }

            } else {
                if (ig_md.stream_gate.gate_closed_due_to_octets_exceeded_enable){
                    ig_md.stream_gate.reset_octets = set_reset_octets_flag.execute(ig_md.stream_gate.interval_identifier);

                    if (ig_md.stream_gate.reset_octets == true){
                        // New period
                        reset_octets.execute(ig_md.stream_gate.interval_identifier);
                        set_first_sdu.execute(ig_md.stream_gate.interval_identifier);
                    }
                    else {
                        // Get remaining octets
                        ig_md.stream_gate.remaining_octets = decrement_octets.execute(ig_md.stream_gate.interval_identifier);
                        // Check if drop is needed
                        ig_dprsr_md.drop_ctl = get_first_sdu.execute(ig_md.stream_gate.interval_identifier);
                    }
                }

                if (ig_dprsr_md.drop_ctl == 1){
                    // Frame is to be dropped because of octetsExceeded, permanently block the gate
                    block_gate.execute(ig_md.stream_filter.stream_gate_id);
                } else {
                    if (ig_md.stream_gate.PSFPGateEnabled == 0) {
                        // Packet is out of schedule, drop it
                        ig_dprsr_md.drop_ctl = 1;

                        // Counter object for frames not passing stream gate
                        not_passed_gate_counter.count(ig_md.stream_filter.stream_gate_id);

                        if (ig_md.stream_gate.gate_closed_due_to_invalid_rx_enable){
                                // Permanently close the gate
                                block_gate.execute(ig_md.stream_filter.stream_gate_id);
                        }
                    } else {
                        // Check if gate is already permanently closed
                        ig_md.stream_gate.gate_closed = get_gate_state.execute(ig_md.stream_filter.stream_gate_id);
                        if ((ig_md.stream_gate.gate_closed_due_to_invalid_rx_enable || ig_md.stream_gate.gate_closed_due_to_octets_exceeded_enable) && ig_md.stream_gate.gate_closed == 1){
                            ig_dprsr_md.drop_ctl = 1;
                        }
                    }
                }


                if (ig_md.stream_gate.ipv == 8){
                    // Set the queue ID according to the Internal Priority Value (IPV)
                    // IPV of 8 means that it shall be ignored and PCP will be used
                    ig_tm_md.qid = (bit<5>)hdr.eth_802_1q.pcp;
                } else {
                    ig_tm_md.qid = (bit<5>)ig_md.stream_gate.ipv;
                }
            }
        }
    }
}
