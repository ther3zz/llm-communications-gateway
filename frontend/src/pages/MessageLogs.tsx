import { useEffect, useState } from 'react';
import axios from 'axios';
import { Phone, MessageSquare, ArrowLeft, ArrowRight, User, FileText, X } from 'lucide-react';

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
    user_label?: string;
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
    user_label?: string;
    chat_id?: string;
    direction?: string;
}

interface OpenWebUIUser {
    id: string;
    name: string;
    email: string;
    role: string;
}

export default function MessageLogs() {
    const [view, setView] = useState<'sms' | 'voice'>('sms');
    const [smsData, setSmsData] = useState<{ logs: Log[], total: number }>({ logs: [], total: 0 });
    const [voiceData, setVoiceData] = useState<{ logs: CallLog[], total: number }>({ logs: [], total: 0 });
    const [loading, setLoading] = useState(false);
    const [page, setPage] = useState(1);
    const [viewTranscription, setViewTranscription] = useState<CallLog | null>(null);
    const [users, setUsers] = useState<OpenWebUIUser[]>([]);
    const [filteredUser, setFilteredUser] = useState<string>('');
    const limit = 50;

    useEffect(() => {
        // Fetch users for filtering
        const fetchUsers = async () => {
            try {
                const res = await axios.get('/api/integrations/openwebui/users');
                setUsers(res.data);
                if (res.data.length > 0 && !filteredUser) {
                    // Start with no user? Or first? User asked for "Required".
                    // Let's default to empty and ask them to select, or auto-select first.
                    // "make it so that a user id is required"
                    // If I select first, it works immediately.
                    setFilteredUser(res.data[0].id);
                }
            } catch (e) { console.error("Failed to fetch users", e); }
        };
        fetchUsers();
    }, []);

    useEffect(() => {
        setPage(1); // Reset page on view switch
        if (view === 'sms') fetchSmsLogs(0);
        else {
            // Only fetch if we have a user, or if we want to clear.
            if (filteredUser) fetchVoiceLogs(0);
            else setVoiceData({ logs: [], total: 0 }); // Clear if no user
        }
    }, [view, filteredUser]);

    useEffect(() => {
        if (view === 'sms') fetchSmsLogs((page - 1) * limit);
        else if (filteredUser) fetchVoiceLogs((page - 1) * limit);
    }, [page]);

    const fetchSmsLogs = async (skip: number) => {
        setLoading(true);
        try {
            const res = await axios.get(`/api/logs?skip=${skip}&limit=${limit}`);
            setSmsData(res.data);
        } catch (e) { console.error(e); } finally { setLoading(false); }
    };

    const fetchVoiceLogs = async (skip: number) => {
        if (!filteredUser) return;
        setLoading(true);
        try {
            const res = await axios.get(`/api/logs/calls?user_id=${filteredUser}&skip=${skip}&limit=${limit}`);
            setVoiceData(res.data);
        } catch (e) {
            console.error(e);
            setVoiceData({ logs: [], total: 0 });
        } finally { setLoading(false); }
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

                <div className="flex gap-4 items-center">
                    {view === 'voice' && (
                        <div className="relative">
                            <select
                                value={filteredUser}
                                onChange={(e) => setFilteredUser(e.target.value)}
                                className="form-select bg-slate-800 border-slate-700 text-sm py-1.5 rounded-md text-slate-300"
                                style={{ width: '200px' }}
                            >
                                <option value="" disabled>Select User</option>
                                {users.map(u => (
                                    <option key={u.id} value={u.id}>{u.name} ({u.email})</option>
                                ))}
                            </select>
                        </div>
                    )}

                    <div className="toggle-group">
                        <button
                            onClick={() => setView('sms')}
                            className={`toggle-btn ${view === 'sms' ? 'active' : ''}`}
                        >
                            <MessageSquare size={14} /> SMS
                        </button>
                        <button
                            onClick={() => setView('voice')}
                            className={`toggle-btn ${view === 'voice' ? 'active' : ''}`}
                        >
                            <Phone size={14} /> VoiceCalls
                        </button>
                    </div>
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
                                                            <span className="font-mono opacity-80">
                                                                {log.user_label ? log.user_label : `${log.user_id.slice(0, 6)}...`}
                                                            </span>
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
                                                            <span className="font-mono opacity-80">
                                                                {log.user_label ? log.user_label : `${log.user_id.slice(0, 6)}...`}
                                                            </span>
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
                                        <td>
                                            {log.transcription ? (
                                                <button
                                                    onClick={() => setViewTranscription(log)}
                                                    className="btn-ghost text-slate-400 hover:text-indigo-400 text-sm"
                                                    title="View Transcription"
                                                >
                                                    <FileText size={16} /> <span className="underline decoration-slate-600 underline-offset-4">View</span>
                                                </button>
                                            ) : (
                                                <span className="text-slate-600 italic text-sm">-</span>
                                            )}
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

            {/* Modal */}
            {
                viewTranscription && (
                    <div className="modal-overlay" onClick={() => setViewTranscription(null)}>
                        <div className="modal-content" onClick={e => e.stopPropagation()}>
                            <div className="modal-header">
                                <h3 className="modal-title">Call Transcription</h3>
                                <button onClick={() => setViewTranscription(null)} className="modal-close">
                                    <X size={20} />
                                </button>
                            </div>
                            <div className="mb-4 text-sm text-slate-400 grid grid-cols-2 gap-4">
                                <div>
                                    <span className="block text-slate-500 text-xs uppercase tracking-wider mb-1">Date</span>
                                    {new Date(viewTranscription.timestamp).toLocaleString()}
                                </div>
                                <div>
                                    <span className="block text-slate-500 text-xs uppercase tracking-wider mb-1">Direction</span>
                                    <span className="capitalize">{viewTranscription.direction || 'Outbound'}</span>
                                </div>
                                <div>
                                    <span className="block text-slate-500 text-xs uppercase tracking-wider mb-1">From</span>
                                    {viewTranscription.from_number || '-'}
                                </div>
                                <div>
                                    <span className="block text-slate-500 text-xs uppercase tracking-wider mb-1">To</span>
                                    {viewTranscription.to_number}
                                </div>
                            </div>
                            <div className="chat-container">
                                {(() => {
                                    const txt = viewTranscription.transcription || '';
                                    if (!txt.includes('User:') && !txt.includes('Assistant:')) {
                                        return <div className="transcription-text">{txt}</div>;
                                    }
                                    const segments = txt.split(/(User|Assistant|System):/g).filter(s => s.trim());
                                    const msgs = [];
                                    for (let i = 0; i < segments.length; i += 2) {
                                        if (i + 1 < segments.length) {
                                            msgs.push({ role: segments[i], content: segments[i + 1] });
                                        }
                                    }
                                    return msgs.map((m, i) => (
                                        <div key={i} className={`chat-message ${m.role.toLowerCase()}`}>
                                            <div className="chat-role">{m.role}</div>
                                            <div>{m.content}</div>
                                        </div>
                                    ));
                                })()}
                            </div>
                        </div>
                    </div>
                )
            }
        </div >
    );
}
