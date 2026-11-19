// Extension 4: clean-channel SimPy/ns-3 comparison with observed Wi-Fi TIDs.
#include "ns3/core-module.h"
#include "ns3/internet-module.h"
#include "ns3/mobility-module.h"
#include "ns3/network-module.h"
#include "ns3/wifi-module.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <numeric>
#include <stdexcept>
#include <string>
#include <vector>

using namespace ns3;

namespace
{

constexpr std::array<const char*, 4> names{"VO", "VI", "BE", "BK"};
constexpr std::array<AcIndex, 4> accessCategories{AC_VO, AC_VI, AC_BE, AC_BK};
constexpr std::array<uint8_t, 4> tos{0xC0, 0x80, 0x00, 0x20};
constexpr std::array<uint32_t, 4> payloadBytes{100, 1000, 1500, 500};
constexpr uint16_t firstPort = 9000;

class DelayTag : public Tag
{
  public:
    static TypeId GetTypeId()
    {
        static TypeId tid =
            TypeId("ns3::CrosscheckDelayTag").SetParent<Tag>().AddConstructor<DelayTag>();
        return tid;
    }

    TypeId GetInstanceTypeId() const override { return GetTypeId(); }
    uint32_t GetSerializedSize() const override { return 8; }
    void Serialize(TagBuffer buffer) const override { buffer.WriteU64(createdNs); }
    void Deserialize(TagBuffer buffer) override { createdNs = buffer.ReadU64(); }
    void Print(std::ostream& out) const override { out << createdNs; }

    uint64_t createdNs{};
};

NS_OBJECT_ENSURE_REGISTERED(DelayTag);

uint32_t
TrafficClass(uint32_t station, uint32_t stations)
{
    if (station < 2)
    {
        return 0;
    }
    if (station < 4)
    {
        return 1;
    }
    return (station - 4 < (stations - 3) / 2) ? 2 : 3;
}

bool
IsPeriodic(uint32_t ac)
{
    return ac < 2;
}

class TrafficSource : public Application
{
  public:
    TrafficSource(uint32_t ac, Ipv4Address remote, Time stop)
        : m_ac(ac),
          m_remote(remote),
          m_stop(stop)
    {
    }

    void Watch(Ptr<WifiMac> mac)
    {
        if (IsPeriodic(m_ac))
        {
            return;
        }
        const bool ack = mac->TraceConnectWithoutContext(
            "AckedMpdu", MakeCallback(&TrafficSource::Acked, this));
        const bool drop = mac->TraceConnectWithoutContext(
            "DroppedMpdu", MakeCallback(&TrafficSource::Dropped, this));
        if (!ack || !drop)
        {
            throw std::runtime_error("missing MAC completion trace");
        }
    }

  private:
    void StartApplication() override
    {
        m_socket = Socket::CreateSocket(GetNode(), UdpSocketFactory::GetTypeId());
        if (m_socket->Bind() < 0 ||
            m_socket->Connect(InetSocketAddress(m_remote, firstPort + m_ac)) < 0)
        {
            throw std::runtime_error("could not open traffic socket");
        }
        m_socket->SetIpTos(tos[m_ac]);
        SendOne();
    }

    void StopApplication() override
    {
        m_next.Cancel();
        m_socket->Close();
        m_socket = nullptr;
    }

    void SendOne()
    {
        if (!m_socket || Simulator::Now() >= m_stop)
        {
            return;
        }
        Ptr<Packet> packet = Create<Packet>(payloadBytes[m_ac]);
        DelayTag tag;
        tag.createdNs = Simulator::Now().GetNanoSeconds();
        packet->AddPacketTag(tag);
        if (m_socket->Send(packet) < 0)
        {
            throw std::runtime_error("could not enqueue application packet");
        }
        if (IsPeriodic(m_ac))
        {
            m_next = Simulator::Schedule(MilliSeconds(10), &TrafficSource::SendOne, this);
        }
    }

    void Acked(Ptr<const WifiMpdu> mpdu)
    {
        DelayTag tag;
        if (m_socket && Simulator::Now() < m_stop && mpdu->GetPacket()->PeekPacketTag(tag))
        {
            // One outstanding application frame per saturated station.
            m_next = Simulator::ScheduleNow(&TrafficSource::SendOne, this);
        }
    }

    void Dropped(WifiMacDropReason, Ptr<const WifiMpdu> mpdu) { Acked(mpdu); }

    uint32_t m_ac;
    Ipv4Address m_remote;
    Time m_stop;
    Ptr<Socket> m_socket;
    EventId m_next;
};

class DelaySink : public Application
{
  public:
    DelaySink(uint32_t ac, Time start, Time stop)
        : m_ac(ac),
          m_start(start),
          m_stop(stop)
    {
    }

    uint64_t bytes{};
    std::vector<double> delaysMs;

  private:
    void StartApplication() override
    {
        m_socket = Socket::CreateSocket(GetNode(), UdpSocketFactory::GetTypeId());
        if (m_socket->Bind(InetSocketAddress(Ipv4Address::GetAny(), firstPort + m_ac)) < 0)
        {
            throw std::runtime_error("could not bind delay sink");
        }
        m_socket->SetRecvCallback(MakeCallback(&DelaySink::Receive, this));
    }

    void StopApplication() override { m_socket->Close(); }

    void Receive(Ptr<Socket> socket)
    {
        while (Ptr<Packet> packet = socket->Recv())
        {
            const Time now = Simulator::Now();
            DelayTag tag;
            if (now >= m_start && now < m_stop && packet->PeekPacketTag(tag))
            {
                delaysMs.push_back((now.GetNanoSeconds() - tag.createdNs) / 1e6);
                bytes += packet->GetSize();
            }
        }
    }

    uint32_t m_ac;
    Time m_start;
    Time m_stop;
    Ptr<Socket> m_socket;
};

struct TxStats
{
    Time start;
    Time stop;
    bool qos;
    std::array<uint64_t, 4> attempts{};
    std::array<uint64_t, 4> matches{};
    std::array<unsigned, 4> tidMasks{};
};

void
CountTransmission(TxStats* stats, uint32_t expected, Ptr<const Packet> packet, Watt_u)
{
    const Time now = Simulator::Now();
    DelayTag tag;
    if (now < stats->start || now >= stats->stop || !packet->PeekPacketTag(tag))
    {
        return;
    }
    WifiMacHeader header;
    packet->PeekHeader(header);
    if (!header.IsData())
    {
        return;
    }
    ++stats->attempts[expected];
    if (stats->qos && header.IsQosData())
    {
        const auto tid = header.GetQosTid();
        stats->tidMasks[expected] |= 1u << tid;
        if (tid < 8 && QosUtilsMapTidToAc(tid) == accessCategories[expected])
        {
            ++stats->matches[expected];
        }
    }
}

double
Percentile(const std::vector<double>& sorted, double q)
{
    const double pos = (sorted.size() - 1) * q;
    const auto lo = static_cast<size_t>(pos);
    const auto hi = std::min(lo + 1, sorted.size() - 1);
    return sorted[lo] + (pos - lo) * (sorted[hi] - sorted[lo]);
}

void
ConfigureMac(Ptr<WifiMac> mac, bool qos)
{
    mac->SetFrameRetryLimit(8);
    if (!qos)
    {
        auto txop = mac->GetTxop();
        txop->SetAifsn(2);
        txop->SetMinCw(15);
        txop->SetMaxCw(1023);
        txop->SetTxopLimit(Seconds(0));
        return;
    }
    constexpr std::array<uint8_t, 4> aifsn{2, 2, 3, 7};
    constexpr std::array<uint32_t, 4> cwMin{3, 7, 15, 15};
    constexpr std::array<uint32_t, 4> cwMax{7, 15, 1023, 1023};
    for (uint32_t ac = 0; ac < names.size(); ++ac)
    {
        auto txop = mac->GetQosTxop(accessCategories[ac]);
        if (!txop)
        {
            throw std::runtime_error("expected a QoS transmit queue");
        }
        txop->SetAifsn(aifsn[ac]);
        txop->SetMinCw(cwMin[ac]);
        txop->SetMaxCw(cwMax[ac]);
        txop->SetTxopLimit(Seconds(0));
    }
}

void
Run(const char* output, int stations, const std::string& mode, double duration, int seed)
{
    if (stations < 6 || stations > 253 || !std::isfinite(duration) || duration <= 0 ||
        seed <= 0 || (mode != "DCF" && mode != "EDCA"))
    {
        throw std::invalid_argument("require 6-253 stations, positive duration and seed, and DCF or EDCA");
    }
    const Time start = Seconds(2);
    const Time stop = start + Seconds(duration);
    const bool qos = mode == "EDCA";
    TxStats stats{start, stop, qos};
    RngSeedManager::SetSeed(seed);
    RngSeedManager::SetRun(1);

    NodeContainer staNodes;
    staNodes.Create(stations);
    NodeContainer apNode;
    apNode.Create(1);
    NodeContainer nodes(apNode, staNodes);

    YansWifiChannelHelper channel = YansWifiChannelHelper::Default();
    YansWifiPhyHelper phy;
    phy.SetChannel(channel.Create());
    phy.Set("ChannelSettings", StringValue("{36, 20, BAND_5GHZ, 0}"));
    WifiHelper wifi;
    wifi.SetStandard(WIFI_STANDARD_80211a);
    wifi.SetRemoteStationManager("ns3::ConstantRateWifiManager",
                                 "DataMode", StringValue("OfdmRate54Mbps"),
                                 "ControlMode", StringValue("OfdmRate54Mbps"),
                                 "RtsCtsThreshold", UintegerValue(65535),
                                 "FragmentationThreshold", UintegerValue(65535));
    WifiMacHelper mac;
    const Ssid ssid("edca-crosscheck");
    mac.SetType("ns3::StaWifiMac", "QosSupported", BooleanValue(qos),
                "Ssid", SsidValue(ssid), "ActiveProbing", BooleanValue(false));
    auto staDevices = wifi.Install(phy, mac, staNodes);
    mac.SetType("ns3::ApWifiMac", "QosSupported", BooleanValue(qos), "Ssid", SsidValue(ssid),
                "EnableBeaconJitter", BooleanValue(false));
    auto apDevices = wifi.Install(phy, mac, apNode);

    // Put all stations at the same location to exclude hidden terminals,
    // propagation-distance differences and capture asymmetry.
    auto positions = CreateObject<ListPositionAllocator>();
    positions->Add(Vector(0, 0, 0));
    for (int i = 0; i < stations; ++i)
    {
        positions->Add(Vector(1, 0, 0));
    }
    MobilityHelper mobility;
    mobility.SetPositionAllocator(positions);
    mobility.SetMobilityModel("ns3::ConstantPositionMobilityModel");
    mobility.Install(nodes);

    InternetStackHelper internet;
    internet.Install(nodes);
    Ipv4AddressHelper ipv4;
    ipv4.SetBase("10.1.1.0", "255.255.255.0");
    const auto apAddress = ipv4.Assign(apDevices).GetAddress(0);
    ipv4.Assign(staDevices);
    ConfigureMac(DynamicCast<WifiNetDevice>(apDevices.Get(0))->GetMac(), qos);

    std::array<Ptr<DelaySink>, 4> sinks;
    for (uint32_t ac = 0; ac < names.size(); ++ac)
    {
        sinks[ac] = CreateObject<DelaySink>(ac, start, stop);
        apNode.Get(0)->AddApplication(sinks[ac]);
        sinks[ac]->SetStartTime(Seconds(0.5));
        sinks[ac]->SetStopTime(stop);
    }
    for (uint32_t i = 0; i < staNodes.GetN(); ++i)
    {
        const uint32_t ac = TrafficClass(i, stations);
        auto device = DynamicCast<WifiNetDevice>(staDevices.Get(i));
        ConfigureMac(device->GetMac(), qos);
        if (!device->GetPhy()->TraceConnectWithoutContext(
                "PhyTxBegin", MakeBoundCallback(&CountTransmission, &stats, ac)))
        {
            throw std::runtime_error("could not attach PHY transmit trace");
        }
        auto source = CreateObject<TrafficSource>(ac, apAddress, stop);
        staNodes.Get(i)->AddApplication(source);
        source->Watch(device->GetMac());
        source->SetStartTime(start);
        source->SetStopTime(stop);
    }

    Simulator::Stop(stop);
    Simulator::Run();
    Simulator::Destroy();

    for (uint32_t ac = 0; ac < names.size(); ++ac)
    {
        if (stats.attempts[ac] == 0 || (qos && stats.matches[ac] != stats.attempts[ac]))
        {
            throw std::runtime_error(std::string("unverified MAC traffic category ") + names[ac]);
        }
    }
    std::ofstream out(std::filesystem::u8path(output));
    if (!out)
    {
        throw std::runtime_error("could not write cross-check CSV");
    }
    out << "mode,stations,seed,duration_s,external_busy_fraction,ac,frames,throughput_mbps,"
           "mean_ms,p99_ms,p999_ms,attempts,qos_matched_attempts,tid_mask\n";
    out << std::setprecision(15);
    for (uint32_t ac = 0; ac < names.size(); ++ac)
    {
        auto& delays = sinks[ac]->delaysMs;
        std::sort(delays.begin(), delays.end());
        out << mode << ',' << stations << ',' << seed << ',' << duration << ",0," << names[ac]
            << ',' << delays.size() << ',' << sinks[ac]->bytes * 8.0 / duration / 1e6 << ',';
        if (!delays.empty())
        {
            out << std::accumulate(delays.begin(), delays.end(), 0.0) / delays.size() << ','
                << Percentile(delays, 0.99) << ',' << Percentile(delays, 0.999);
        }
        else
        {
            out << ",,";
        }
        out << ',' << stats.attempts[ac] << ',' << stats.matches[ac] << ',' << stats.tidMasks[ac]
            << '\n';
    }
    if (!out)
    {
        throw std::runtime_error("failed while writing cross-check CSV");
    }
}

} // namespace

#ifdef WIFI_CROSSCHECK_DLL
#ifdef _WIN32
#define WIFI_CROSSCHECK_EXPORT __declspec(dllexport)
#else
#define WIFI_CROSSCHECK_EXPORT
#endif
extern "C" WIFI_CROSSCHECK_EXPORT int
run_scenario(const char* path, int stations, int mode, double duration, int seed)
{
    try
    {
        Run(path, stations, mode == 0 ? "DCF" : mode == 1 ? "EDCA" : "", duration, seed);
        return 0;
    }
    catch (const std::exception& error)
    {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
#else
int
main(int argc, char* argv[])
{
    int stations = 10;
    int seed = 42;
    double duration = 10;
    std::string mode = "EDCA";
    std::string out = "ns3_crosscheck.csv";
    CommandLine cmd(__FILE__);
    cmd.AddValue("stations", "Number of stations", stations);
    cmd.AddValue("seed", "Random seed", seed);
    cmd.AddValue("duration", "Measurement window in seconds", duration);
    cmd.AddValue("mode", "DCF or EDCA", mode);
    cmd.AddValue("out", "Output CSV path", out);
    cmd.Parse(argc, argv);
    try
    {
        Run(out.c_str(), stations, mode, duration, seed);
        return 0;
    }
    catch (const std::exception& error)
    {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
#endif
