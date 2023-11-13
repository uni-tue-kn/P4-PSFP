// Preprocessing stuff
#ifndef __STREAM_ID_SIZE__
#define __STREAM_ID_SIZE__ 2048
#endif
#ifndef __STREAM_ID__
#define __STREAM_ID__ 3
#endif
#ifndef __STREAM_GATE_SIZE__
#define __STREAM_GATE_SIZE__ 2048
#endif


#ifndef _HEADERS_
#define _HEADERS_

typedef bit<48> mac_addr_t;
typedef bit<32> ipv4_addr_t;
typedef bit<32> reg_index_t;
/*
Using a physical front panel port for recirculation as 
the reserved recirculation port 68 is used for packet generation.
Port 69..71 are configured in 25 Gbps and aggregated to 100 Gbps in Port 68
*/
const PortId_t RECIRCULATE_PORT_PIPE0 = 8;      // FRONT PANEL PORT 15
const PortId_t RECIRCULATE_PORT_PIPE0_3 = 0;      // FRONT PANEL PORT 16
const PortId_t RECIRCULATE_PORT_PIPE0_2 = 4;    // FRONT PANEL PORT 17
const PortId_t RECIRCULATE_PORT_PIPE0_4 = 12;    // FRONT PANEL PORT 18
const PortId_t RECIRCULATE_PORT_PIPE2_1 = 184;    // Front Panel Port 25
const PortId_t RECIRCULATE_PORT_PIPE2_2 = 176;    // Front Panel Port 26
const PortId_t PACKET_GEN_PORT_PIPE0 = 68;      // Pipe 0
const PortId_t PACKET_GEN_PORT_PIPE1 = 196;     // Pipe 1

const bit<64> MAXIMUM_48_BIT_TS = 281474976710655;

enum bit<16> ether_type_t {
    IPV4  = 0x0800,
    ETH_802_1Q  = 0x8100
}

enum bit<8> ip_type_t {
    TCP = 6,
    UDP = 17
}

header ethernet_t {
    mac_addr_t dst_addr;
    mac_addr_t src_addr;
    bit<16> ether_type;
}

header transport_t{
    bit<16> srcPort;
    bit<16> dstPort;
}

header eth_802_1q_t {
    // ether_type from upper ethernet header is 0x8100 and first two bytes (already parsed in ethernet)
    bit<3> pcp; // Priority Code Point
    bit<1> dei; // Drop Eligible Indicator
    bit<12> vid; // VLAN indicator
    bit<16> ether_type;
}

header ipv4_t {
    bit<4> version;
    bit<4> ihl;
    bit<6> diffserv;
    bit<2> ecn;
    bit<16> total_len;
    bit<16> identification;
    bit<3> flags;
    bit<13> frag_offset;
    bit<8> ttl;
    bit<8> protocol;
    bit<16> hdr_checksum;
    ipv4_addr_t srcAddr;
    ipv4_addr_t dstAddr;
}

/*
This header will be recirculated from egress back to ingress
*/
header recirc_t {
    bit<16> pkt_len;
    bit<32> period_count;
}

/*
This header will be bridged only from ingress to egress before recirculation
*/
header bridge_t {
    bit<64> diff_ts;                // Relative position in hyperperiod
    bit<64> ingress_timestamp;      
    bit<64> hyperperiod_ts;         // Register value of last hyperperiod
    bit<16> ingress_port;
    bit<64> offset;
    bit<32> period_count;           // Used for OctectsExceeded param of stream gate
}
/*
This header will be recirculated from egress back to ingress. 
It is a separate header to contain the 20-bit field inside its own container
*/
header recirc_time_t {
    bit<20> match_ts;
    @padding bit<12> _pad1;
}

struct header_t {
    pktgen_timer_header_t timer;
    recirc_t recirc;
    bridge_t bridge;
    recirc_time_t recirc_time;
    ethernet_t ethernet;
    eth_802_1q_t eth_802_1q;
    ipv4_t ipv4;
    transport_t transport;
}

struct hyperperiod_t {
    bit<48> hyperperiod_ts;                 // Value from hyperperiod register loaded in here
    bit<16> pkt_count_hyperperiod;          // Amount of packets that need to be captured until the hyperperiod TS is updated
    bit<16> pkt_count_register;
    PortId_t port;
}

struct stream_filter_t {
    bit<16> stream_handle;
    bit<1> stream_blocked_due_to_oversize_frame;  // Max SDU exceeded, stream blocked permanently
    bool stream_blocked_due_to_oversize_frame_enable;
    bool active_stream_identification;          // Flag if header values will be overwritten on stream identification
    bit<12> stream_gate_id;
    bit<16> flow_meter_instance_id;
}

struct stream_gate_t {
    bit<4> ipv;
    bit<1> PSFPGateEnabled;
    bit<32> max_octects_interval;
    bit<32> initial_sdu;
    bool reset_octets;
    bit<32> remaining_octets;
    bit<12> interval_identifier;
    bool gate_closed_due_to_invalid_rx_enable;
    bool gate_closed_due_to_octets_exceeded_enable;
    bit<1> gate_closed;
}

struct flow_meter_t {
    bit<2> color;
    bool drop_on_yellow;
    bit<1> meter_blocked;
    bool mark_all_frames_red_enable;
    bool color_aware;                       // true means packets labeled yellow from previous bridges will not be able to be labeled back to green
    MeterColor_t pre_color;
}

struct ingress_metadata_t {
    stream_filter_t stream_filter;
    stream_gate_t stream_gate;
    flow_meter_t flow_meter;
    hyperperiod_t hyperperiod;
    bit<64> diff_ts;
    bit<1> to_be_dropped;
    bit<3> block_reason;
}

struct bytes_in_period_t {
    bit<32> period_id;
    bit<32> octects_in_this_period;
}

/*
Reason corresponds to the digest_type set and tells the control plane why and what to close.
    1: not used
    2: not used
    3: Block FlowMeter due to exceeding bandwidth (marked red by flow meter)
    4: not used
    5: not used
    6: Indicate that a full hyperperiod is finished.
*/
struct digest_block_t {
    bit<16> stream_handle;
    bit<12> stream_gate_id;
    bit<3> drop_ctl;
    bit<1> PSFPGateEnabled;
    bit<3> reason;
    bit<2> color;
    bit<16> flow_meter_instance_id;
}

struct digest_finished_hyperperiod_t {
    PortId_t ingress_port;
    bit<3> app_id;
    bit<2> pipe_id;
    bit<48> ingress_ts;
    bit<3> reason;
}

struct digest_debug_pktgen_t {
    bit<2> pipe_id;
    bit<3> app_id;
    bit<16> batch_id;
    bit<16> packet_id;
    PortId_t ingress_port;
}

struct digest_debug_gate_t {
    bit<20> rel_pos;
    bit<12> stream_gate_id;
    bit<64> diff_ts;                // Relative position in hyperperiod
    bit<64> ingress_timestamp;      
    bit<64> hyperperiod_ts;         // Register value of last hyperperiod
    PortId_t ingress_port;
    bit<32> period_count;
    bit<16> pkt_len;
}

struct egress_metadata_t {
    bit<64> difference_max_to_hyperperiod;
    bit<64> rel_ts_plus_offset;
    bit<64> hyperperiod_duration;
    bit<64> new_rel_pos_with_offset;
    bit<64> offset;
    bit<64> hyperperiod_minus_offset;
}

#endif /* _HEADERS_ */