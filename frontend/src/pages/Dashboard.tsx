import { useEffect, useState } from 'react';
import axios from 'axios';
import { BarChart, DollarSign, MessageSquare, Phone } from 'lucide-react';

interface Log {
    id: number;
    provider_used?: string;
    destination?: string; // SMS
    to_number?: string;   // Voice
    status: string;
    cost: number;
    timestamp: string;
    type?: 'sms' | 'voice';
}

export default function Dashboard() {
    const [combinedLogs, setCombinedLogs] = useState<Log[]>([]);

    const [stats, setStats] = useState({
        smsTotal: 0,
        smsCost: 0,
        voiceTotal: 0,
        voiceCost: 0,
        totalCost: 0
    });

    useEffect(() => {
        fetchStats();
        const interval = setInterval(fetchStats, 5000);
        return () => clearInterval(interval);
    }, []);

    const fetchStats = async () => {
        try {
            const res = await axios.get('/api/stats?limit=20');
            const data = res.data;

            // Handle new structure
            const sLogs = data.sms?.logs || [];
            const vLogs = data.voice?.logs || [];

            // Combine for activity feed
            const combined = [
                ...sLogs.map((l: any) => ({ ...l, type: 'sms' })),
                ...vLogs.map((l: any) => ({ ...l, type: 'voice', destination: l.to_number }))
            ].sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
                .slice(0, 20);

            setCombinedLogs(combined);

            const sCost = sLogs.reduce((acc: number, log: any) => acc + (log.cost || 0), 0);
            const vCost = vLogs.reduce((acc: number, log: any) => acc + (log.cost || 0), 0);

            setStats({
                smsTotal: data.sms?.total || 0,
                smsCost: sCost,
                voiceTotal: data.voice?.total || 0,
                voiceCost: vCost,
                totalCost: sCost + vCost
            });
        } catch (e) {
            console.error("Failed to fetch stats", e);
        }
    };

    return (
        <div>
            <div className="grid-3">
                <StatsCard icon={<MessageSquare color="var(--accent-blue)" />} label="Total SMS" value={stats.smsTotal.toString()} />
                <StatsCard icon={<Phone color="var(--accent-green)" />} label="Total Calls" value={stats.voiceTotal.toString()} />
                <StatsCard icon={<DollarSign color="var(--accent-yellow)" />} label="Est. Recent Cost" value={`$${stats.totalCost.toFixed(4)}`} />
            </div>

            <div className="card">
                <h2 className="card-title">
                    <BarChart size={20} className="text-slate-400" />
                    Recent Activity
                </h2>

                <div className="table-container">
                    <table>
                        <thead>
                            <tr>
                                <th>Time</th>
                                <th>Type</th>
                                <th>Destination</th>
                                <th>Status</th>
                                <th className="text-right">Cost</th>
                            </tr>
                        </thead>
                        <tbody>
                            {combinedLogs.map((log) => (
                                <tr key={`${log.type}-${log.id}`}>
                                    <td>{new Date(log.timestamp).toLocaleTimeString()}</td>
                                    <td>
                                        <span style={{
                                            display: 'flex', alignItems: 'center', gap: '0.5rem',
                                            color: log.type === 'voice' ? 'var(--accent-green)' : 'var(--accent-blue)'
                                        }}>
                                            {log.type === 'voice' ? <Phone size={14} /> : <MessageSquare size={14} />}
                                            <span style={{ textTransform: 'capitalize' }}>{log.type}</span>
                                        </span>
                                    </td>
                                    <td>{log.destination || log.to_number}</td>
                                    <td>
                                        <span className={`badge ${log.status === 'sent' || log.status === 'completed' ? 'badge-sent' :
                                            log.status === 'failed' ? 'badge-failed' : 'badge-default'
                                            }`}>
                                            {log.status}
                                        </span>
                                    </td>
                                    <td className="text-right">${(log.cost || 0).toFixed(4)}</td>
                                </tr>
                            ))}
                            {combinedLogs.length === 0 && (
                                <tr>
                                    <td colSpan={5} className="text-center" style={{ padding: '2rem' }}>No activity found</td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    );
}

function StatsCard({ icon, label, value }: { icon: React.ReactNode, label: string, value: string }) {
    return (
        <div className="card stat-card">
            <div className="stat-icon">{icon}</div>
            <div>
                <div className="stat-label">{label}</div>
                <div className="stat-value">{value}</div>
            </div>
        </div>
    )
}
