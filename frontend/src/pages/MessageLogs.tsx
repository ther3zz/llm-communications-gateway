import { useEffect, useState } from 'react';
import axios from 'axios';
import { Phone, MessageSquare, ArrowLeft, ArrowRight, User } from 'lucide-react';

interface Log {
    id: number;
    provider_used: string;
    destination: string;
    status: string;
    cost: number;
    timestamp: string;
    content: string;
    error_message?: string;
    user_id?: string;
    chat_id?: string;
}

interface CallLog {
    id: number;
    to_number: string;
    from_number: string;
    status: string;
    cost: number;
    timestamp: string;
    duration_seconds: number;
    transcription?: string;
    user_id?: string;
    chat_id?: string;
    direction?: string;
}

export default function MessageLogs() {
    const [view, setView] = useState<'sms' | 'voice'>('sms');
    const [smsData, setSmsData] = useState<{ logs: Log[], total: number }>({ logs: [], total: 0 });
    const [voiceData, setVoiceData] = useState<{ logs: CallLog[], total: number }>({ logs: [], total: 0 });
    const [loading, setLoading] = useState(false);
    const [page, setPage] = useState(1);
    const limit = 50;

    useEffect(() => {
        setPage(1); // Reset page on view switch
        if (view === 'sms') fetchSmsLogs(0);
        else fetchVoiceLogs(0);
    }, [view]);

    useEffect(() => {
        if (view === 'sms') fetchSmsLogs((page - 1) * limit);
        else fetchVoiceLogs((page - 1) * limit);
    }, [page]);

    const fetchSmsLogs = async (skip: number) => {
        setLoading(true);
        try {
            const res = await axios.get(`/api/logs?skip=${skip}&limit=${limit}`);
            setSmsData(res.data);
        } catch (e) { console.error(e); } finally { setLoading(false); }
    };

    const fetchVoiceLogs = async (skip: number) => {
        setLoading(true);
        try {
            const res = await axios.get(`/api/logs/calls?skip=${skip}&limit=${limit}`);
            setVoiceData(res.data);
        } catch (e) { console.error(e); } finally { setLoading(false); }
    };

    const currentTotal = view === 'sms' ? smsData.total : voiceData.total;
    const totalPages = Math.ceil(currentTotal / limit);

    return (
        <div>
            <div className="flex justify-between items-center mb-4">
                <div>
                    <h1 className="card-title" style={{ fontSize: '1.5rem', marginBottom: '0.25rem' }}>Logs</h1>
                    <p className="text-slate-400 text-sm">History of communications.</p>
                </div>

                <div className="flex gap-2 bg-slate-800 p-1 rounded-lg">
                    <button
                        onClick={() => setView('sms')}
                        className={`px-3 py-1 rounded-md text-sm flex items-center gap-2 transition-colors ${view === 'sms' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-white'}`}
                    >
                        <MessageSquare size={14} /> SMS
                    </button>
                    <button
                        onClick={() => setView('voice')}
                        className={`px-3 py-1 rounded-md text-sm flex items-center gap-2 transition-colors ${view === 'voice' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-white'}`}
                    >
                        <Phone size={14} /> VoiceCalls
                    </button>
                </div>
            </div>

            <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
                <div className="table-container">
                    {view === 'sms' ? (
                        <table>
                            <thead>
                                <tr>
                                    <th>Time</th>
                                    <th>Provider</th>
                                    <th>Destination</th>
                                    <th>Message</th>
                                    <th>User / Chat</th>
                                    <th>Status</th>
                                    <th>Error</th>
                                    <th className="text-right">Cost</th>
                                </tr>
                            </thead>
                            <tbody style={{ opacity: loading ? 0.5 : 1, transition: 'opacity 0.2s' }}>
                                {smsData.logs.map((log) => (
                                    <tr key={log.id}>
                                        <td style={{ whiteSpace: 'nowrap' }}>{new Date(log.timestamp).toLocaleString()}</td>
                                        <td style={{ textTransform: 'capitalize' }}>{log.provider_used}</td>
                                        <td>{log.destination}</td>
                                        <td style={{ maxWidth: '300px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={log.content}>
                                            {log.content}
                                        </td>
                                        <td>
                                            {(log.user_id || log.chat_id) ? (
                                                <div className="flex flex-col gap-1">
                                                    {log.user_id && (
                                                        <div className="flex items-center gap-1 text-xs text-slate-300 bg-slate-800/50 px-1.5 py-0.5 rounded border border-slate-700/50 w-fit" title={`User ID: ${log.user_id}`}>
                                                            <User size={10} className="text-indigo-400" />
                                                            <span className="font-mono opacity-80">{log.user_id.slice(0, 6)}...</span>
                                                        </div>
                                                    )}
                                                    {log.chat_id && (
                                                        <div className="flex items-center gap-1 text-xs text-slate-300 bg-slate-800/50 px-1.5 py-0.5 rounded border border-slate-700/50 w-fit" title={`Chat ID: ${log.chat_id}`}>
                                                            <MessageSquare size={10} className="text-emerald-400" />
                                                            <span className="font-mono opacity-80">{log.chat_id.slice(0, 6)}...</span>
                                                        </div>
                                                    )}
                                                </div>
                                            ) : (
                                                <span className="text-slate-700">-</span>
                                            )}
                                        </td>
                                        <td>
                                            <span className={`badge ${log.status === 'sent' ? 'badge-sent' : log.status === 'failed' ? 'badge-failed' : 'badge-default'}`}>
                                                {log.status}
                                            </span>
                                        </td>
                                        <td className="text-red-400 text-sm">{log.error_message || '-'}</td>
                                        <td className="text-right">${(log.cost || 0).toFixed(4)}</td>
                                    </tr>
                                ))}
                                {smsData.logs.length === 0 && (
                                    <tr><td colSpan={7} className="text-center" style={{ padding: '3rem' }}>No SMS messages found</td></tr>
                                )}
                            </tbody>
                        </table>
                    ) : (
                        <table>
                            <thead>
                                <tr>
                                    <th>Time</th>
                                    <th>Direction</th>
                                    <th>To</th>
                                    <th>From</th>
                                    <th>User / Chat</th>
                                    <th>Duration</th>
                                    <th>Status</th>
                                    <th className="text-right">Cost</th>
                                    <th>Transcription</th>
                                </tr>
                            </thead>
                            <tbody style={{ opacity: loading ? 0.5 : 1, transition: 'opacity 0.2s' }}>
                                {voiceData.logs.map((log) => (
                                    <tr key={log.id}>
                                        <td className="text-sm text-slate-400" style={{ whiteSpace: 'nowrap' }}>
                                            {new Date(log.timestamp).toLocaleString()}
                                        </td>
                                        <td>
                                            <span className={`badge ${log.direction === 'inbound' ? 'badge-blue' : 'badge-purple'}`}>
                                                {log.direction === 'inbound' ? <ArrowLeft size={12} /> : <ArrowRight size={12} />}
                                                <span className="ml-1 capitalize">{log.direction || 'outbound'}</span>
                                            </span>
                                        </td>
                                        <td>{log.to_number}</td>
                                        <td>{log.from_number}</td>
                                        <td>
                                            {(log.user_id || log.chat_id) ? (
                                                <div className="flex flex-col gap-1">
                                                    {log.user_id && (
                                                        <div className="flex items-center gap-1 text-xs text-slate-300 bg-slate-800/50 px-1.5 py-0.5 rounded border border-slate-700/50 w-fit" title={`User ID: ${log.user_id}`}>
                                                            <User size={10} className="text-indigo-400" />
                                                            <span className="font-mono opacity-80">{log.user_id.slice(0, 6)}...</span>
                                                        </div>
                                                    )}
                                                    {log.chat_id && (
                                                        <div className="flex items-center gap-1 text-xs text-slate-300 bg-slate-800/50 px-1.5 py-0.5 rounded border border-slate-700/50 w-fit" title={`Chat ID: ${log.chat_id}`}>
                                                            <MessageSquare size={10} className="text-emerald-400" />
                                                            <span className="font-mono opacity-80">{log.chat_id.slice(0, 6)}...</span>
                                                        </div>
                                                    )}
                                                </div>
                                            ) : (
                                                <span className="text-slate-700">-</span>
                                            )}
                                        </td>
                                        <td>{log.duration_seconds || 0}s</td>
                                        <td>
                                            <span className={`badge ${log.status === 'completed' ? 'badge-sent' : log.status === 'failed' ? 'badge-failed' : 'badge-default'}`}>
                                                {log.status}
                                            </span>
                                        </td>
                                        <td className="text-right">${(log.cost || 0).toFixed(4)}</td>
                                        <td style={{ maxWidth: '600px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={log.transcription}>
                                            {log.transcription || <span className="text-slate-600 italic">No input</span>}
                                        </td>
                                    </tr>
                                ))}
                                {voiceData.logs.length === 0 && (
                                    <tr><td colSpan={9} className="text-center" style={{ padding: '3rem' }}>No calls found</td></tr>
                                )}
                            </tbody>
                        </table>
                    )}
                </div>

                {totalPages > 1 && (
                    <div className="flex justify-between items-center p-4 border-t border-slate-700">
                        <button
                            disabled={page === 1}
                            onClick={() => setPage(p => p - 1)}
                            className="btn btn-secondary text-sm disabled:opacity-50 flex items-center gap-1"
                        >
                            <ArrowLeft size={16} /> Previous
                        </button>
                        <span className="text-sm text-slate-400">Page {page} of {totalPages}</span>
                        <button
                            disabled={page === totalPages}
                            onClick={() => setPage(p => p + 1)}
                            className="btn btn-secondary text-sm disabled:opacity-50 flex items-center gap-1"
                        >
                            Next <ArrowRight size={16} />
                        </button>
                    </div>
                )}
            </div>
        </div>
    );
}
