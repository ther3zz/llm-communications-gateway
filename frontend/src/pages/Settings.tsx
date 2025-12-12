import { useEffect, useState } from 'react';
import axios from 'axios';
import { Save, Plus, Trash2, CheckCircle, XCircle, RefreshCw } from 'lucide-react';

interface UtilProvider {
    id?: number;
    name: string;
    api_key: string;
    api_url?: string;
    from_number?: string;
    app_id?: string;
    enabled: boolean;
    priority: number;
    webhook_secret?: string;
    base_url?: string;
    inbound_system_prompt?: string;
    inbound_enabled?: boolean;
    max_call_duration?: number;
    call_limit_message?: string;
}

interface ChatterboxVoice {
    name: string;
    language: string;
}

interface LLMModel {
    id: string;
    object: string;
}

interface VoiceConfig {
    id?: number;
    stt_url: string;
    tts_url: string;
    llm_url: string;
    llm_provider?: string;
    llm_api_key?: string;
    llm_model: string;
    voice_id: string;
    stt_timeout?: number;
    tts_timeout?: number;
    llm_timeout?: number;
    system_prompt?: string;
    send_conversation_context?: boolean;
    rtp_codec?: string;
}

interface EnvDefaults {
    ollama_url?: string;
    openwebui_url?: string;
    base_url?: string;
    system_prompt?: string;
}

export default function Settings() {
    const [providers, setProviders] = useState<UtilProvider[]>([]);
    const [voiceConfig, setVoiceConfig] = useState<VoiceConfig>({
        stt_url: 'http://parakeet:8000',
        tts_url: 'http://chatterbox:8000',
        llm_url: 'http://open-webui:8080/v1',
        llm_provider: 'custom',
        llm_model: 'gpt-3.5-turbo',
        voice_id: 'default',
        stt_timeout: 10,
        tts_timeout: 10,
        llm_timeout: 10,
        send_conversation_context: true,
        rtp_codec: 'PCMU'
    });

    // Voices state
    const [availableVoices, setAvailableVoices] = useState<ChatterboxVoice[]>([]);
    const [availableModels, setAvailableModels] = useState<LLMModel[]>([]);

    const [loading, setLoading] = useState(false);
    const [voiceLoading, setVoiceLoading] = useState(false);

    const [newProvider, setNewProvider] = useState<UtilProvider>({
        name: 'telnyx',
        api_key: '',
        enabled: true,
        priority: 0,
        from_number: '',
        app_id: '',
        inbound_system_prompt: '',
        inbound_enabled: true,
        max_call_duration: 600,
        call_limit_message: "This call has reached its time limit. Goodbye."
    });

    const [editingId, setEditingId] = useState<number | null>(null);

    // LLM Provider Logic
    const [llmProvider, setLlmProvider] = useState<'openai' | 'ollama' | 'openwebui' | 'custom'>('custom');
    const [llmBaseDomain, setLlmBaseDomain] = useState('');
    const [envDefaults, setEnvDefaults] = useState<EnvDefaults>({});

    // useEffect(() => {
    //    if (!voiceConfig.llm_url) return;
    //    // ... heuristic removed in favor of explicit llm_provider logic ...
    // }, [voiceConfig.id]);

    const handleProviderChange = (type: 'openai' | 'ollama' | 'openwebui' | 'custom') => {
        setLlmProvider(type);
        let newUrl = voiceConfig.llm_url;
        if (type === 'openai') {
            // OpenAI usually fixed
            newUrl = 'https://api.openai.com/v1';
        } else if (type === 'ollama') {
            // Use env default or localhost
            const base = envDefaults.ollama_url || 'http://localhost:11434';
            newUrl = `${base.replace(/\/v1$/, '')}/v1`;
            setLlmBaseDomain(base.replace(/\/v1$/, ''));
        } else if (type === 'openwebui') {
            // Use env default or localhost:3000 (usually mapped to 8080 internal)
            // But frontend accesses external URL.
            const base = envDefaults.openwebui_url || 'http://localhost:3000';
            newUrl = `${base.replace(/\/v1$/, '')}/v1`;
            setLlmBaseDomain(base.replace(/\/v1$/, ''));
        }
        setVoiceConfig({ ...voiceConfig, llm_url: newUrl, llm_provider: type });
    };

    const handleBaseDomainChange = (domain: string) => {
        setLlmBaseDomain(domain);
        let suffix = '/v1';
        if (llmProvider === 'openwebui') suffix = '/v1';

        // Remove trailing slash from domain
        const cleanDomain = domain.replace(/\/$/, "");
        setVoiceConfig({ ...voiceConfig, llm_url: `${cleanDomain}${suffix}` });
    };

    useEffect(() => {
        // Fetch Defaults first
        axios.get('/api/config/defaults').then(res => setEnvDefaults(res.data)).catch(e => console.error(e));

        loadProviders();
        loadVoiceConfig();
        fetchVoices(false);
        fetchModels(false);
    }, []);

    const loadProviders = async () => {
        try {
            const res = await axios.get('/api/config/providers');
            setProviders(res.data);
        } catch (e) {
            console.error(e);
        }
    };

    const loadVoiceConfig = async () => {
        try {
            const res = await axios.get('/api/config/voice');
            if (res.data) {
                setVoiceConfig(res.data);
                // Respect saved provider preference if it exists
                if (res.data.llm_provider) {
                    setLlmProvider(res.data.llm_provider as any);

                    // If provider is Open WebUI or Ollama, try to reconstruct base domain
                    if (res.data.llm_provider === 'openwebui' || res.data.llm_provider === 'ollama') {
                        // Extract base domain from URL
                        // e.g. http://localhost:3000/v1 -> http://localhost:3000
                        const url = res.data.llm_url;
                        if (url) {
                            setLlmBaseDomain(url.replace(/\/v1\/?$/, '').replace(/\/api\/?$/, ''));
                        }
                    }
                }
            }
        } catch (e) {
            console.error(e);
        }
    };

    const fetchVoices = async (showFeedback: boolean = false) => {
        try {
            const res = await axios.get('/api/proxies/chatterbox/voices');
            if (res.data && res.data.voices) {
                setAvailableVoices(res.data.voices);
                if (showFeedback) alert(`Found ${res.data.voices.length} voices.`);
            } else {
                if (showFeedback) alert("No voices found or invalid response.");
            }
        } catch (e) {
            console.error(e);
            if (showFeedback) alert("Failed to fetch voices. Check TTS URL and container status.");
        }
    };

    const fetchModels = async (showFeedback: boolean = false) => {
        try {
            const res = await axios.get('/api/proxies/llm/models');
            if (res.data && Array.isArray(res.data.data)) {
                setAvailableModels(res.data.data);
                if (showFeedback) alert(`Found ${res.data.data.length} models.`);
            } else {
                if (showFeedback) alert("No models found or invalid response.");
            }
        } catch (e) {
            console.error(e);
            if (showFeedback) alert("Failed to fetch models. Check LLM URL.");
        }
    };

    const checkParakeet = async () => {
        try {
            const res = await axios.get('/api/proxies/parakeet/status');
            if (res.data && res.data.status === 'ok') {
                alert("Connected to Parakeet successfully!");
            } else {
                alert("Parakeet reachable but returned unexpected status.");
            }
        } catch (e: any) {
            console.error(e);
            const msg = e.response?.data?.detail || "Failed to connect to Parakeet.";
            alert(msg);
        }
    };

    const handleEdit = (p: UtilProvider) => {
        setNewProvider({ ...p, api_key: '' }); // Clear API key to prevent re-sending encrypted value
        setEditingId(p.id || null);
        // Scroll to top
        window.scrollTo({ top: 0, behavior: 'smooth' });
    };

    const handleCancelEdit = () => {
        setNewProvider({ name: 'telnyx', api_key: '', enabled: true, priority: 0, from_number: '', app_id: '', inbound_system_prompt: '', inbound_enabled: true, max_call_duration: 600, call_limit_message: "This call has reached its time limit. Goodbye." });
        setEditingId(null);
    };

    const handleSaveProvider = async () => {
        if (!newProvider.name || (!newProvider.api_key && !editingId)) return;
        setLoading(true);
        try {
            if (editingId) {
                // Remove api_key if empty to avoid overwriting with empty string or re-encrypting checks
                const payload = { ...newProvider };
                if (!payload.api_key) {
                    delete (payload as any).api_key;
                }
                await axios.put(`/api/config/providers/${editingId}`, payload);
            } else {
                await axios.post('/api/config/providers', newProvider);
            }
            handleCancelEdit(); // Reset form
            loadProviders();
        } catch (e) {
            console.error(e);
            alert("Failed to save provider");
        } finally {
            setLoading(false);
        }
    };

    const handleDelete = async (id: number) => {
        if (!confirm("Delete this provider?")) return;
        try {
            await axios.delete(`/api/config/providers/${id}`);
            loadProviders();
        } catch (e) {
            console.error(e);
        }
    };

    const handleSync = async (p: UtilProvider) => {
        if (!p.id || p.name !== 'telnyx') return;
        const url = prompt("Enter the Base URL of your server (e.g. https://myapp.ngrok.io).\nWe will append '/api/voice/webhook?token=...' automatically.", window.location.origin);
        if (!url) return;

        try {
            await axios.post('/api/voice/sync', {
                provider: p.name,
                base_url: url
            });
            alert("Telnyx Application updated successfully with secured Webhook URL!");
        } catch (e: any) {
            console.error(e);
            alert("Failed to sync: " + (e.response?.data?.detail || e.message));
        }
    };

    const handleToggle = async (p: UtilProvider) => {
        if (!p.id) return;
        try {
            await axios.put(`/api/config/providers/${p.id}`, { ...p, enabled: !p.enabled });
            loadProviders();
        } catch (e) {
            console.error(e);
        }
    };



    const handleCreateApp = async () => {
        if (newProvider.name !== 'telnyx') return;
        if (!newProvider.api_key && !editingId) {
            alert("Please enter an API Key first.");
            return;
        }

        const appName = prompt("Enter a name for your new Telnyx Application:", "LLM Gateway Voice App");
        if (!appName) return;

        const baseUrl = prompt("Enter the Base URL of your server (e.g. https://myapp.ngrok.io).", window.location.origin);
        if (!baseUrl) return;

        // If editing and key is blank (masked), we can't create app easily without sending key again or refetching.
        // For simplicity, mostly support this for NEW providers or requires re-entry.
        let apiKeyToUse = newProvider.api_key;
        if (!apiKeyToUse && editingId) {
            // Check if we can proceed? Backend needs key.
            // Actually, we can't do this securely if we don't have the key.
            // Prompt user:
            apiKeyToUse = prompt("Please re-enter your API Key to authorize app creation:") || "";
            if (!apiKeyToUse) return;
        }

        try {
            const res = await axios.post('/api/voice/create-app', {
                provider: 'telnyx',
                name: appName,
                api_key: apiKeyToUse,
                base_url: baseUrl
            });

            if (res.data.app_id) {
                setNewProvider({
                    ...newProvider,
                    app_id: res.data.app_id,
                    webhook_secret: res.data.webhook_secret // Auto-fill the secret too!
                });
                alert(`App created successfully! App ID: ${res.data.app_id}\n\nA new Webhook Secret has also been generated. Please SAVE the provider to persist these changes.`);
            }
        } catch (e: any) {
            console.error(e);
            alert("Failed to create app: " + (e.response?.data?.detail || e.message));
        }
    };

    const handleSaveVoice = async () => {
        setVoiceLoading(true);
        try {
            const res = await axios.post('/api/config/voice', voiceConfig);
            setVoiceConfig(res.data);
            alert("Voice configuration saved!");
        } catch (e) {
            console.error(e);
            alert("Failed to save voice config");
        } finally {
            setVoiceLoading(false);
        }
    };

    return (
        <div style={{ maxWidth: '800px', margin: '0 auto' }}>
            <div className="mb-4">
                <h1 className="card-title" style={{ fontSize: '1.5rem', marginBottom: '0.5rem' }}>Provider Configuration</h1>
                <p className="text-slate-400">Manage your SMS providers and API keys.</p>
            </div>

            {/* Add/Edit Provider */}
            <div className="card">
                <h2 className="card-title">
                    {editingId ? <RefreshCw size={20} color="var(--accent-blue)" /> : <Plus size={20} color="var(--accent-blue)" />}
                    {editingId ? 'Edit Provider' : 'Add Provider'}
                </h2>
                <div className="grid-2 mb-4">
                    <div className="form-group">
                        <label className="form-label">Provider Name</label>
                        <select
                            className="form-select"
                            value={newProvider.name}
                            onChange={e => setNewProvider({ ...newProvider, name: e.target.value })}
                            disabled={!!editingId} // Prevent changing name on edit if we want to enforce consistency, or allow it. Pydantic schema allows. safely allow.
                        >
                            <option value="telnyx">Telnyx</option>
                            <option value="twilio">Twilio (Stub)</option>
                            <option value="commio">Commio (Stub)</option>
                            <option value="mock">Mock Provider</option>
                        </select>
                    </div>
                    <div className="form-group">
                        <label className="form-label">Priority (0 = High)</label>
                        <input
                            type="number"
                            className="form-input"
                            value={newProvider.priority}
                            onChange={e => setNewProvider({ ...newProvider, priority: parseInt(e.target.value) })}
                        />
                    </div>
                    <div className="form-group" style={{ gridColumn: '1 / -1' }}>
                        <label className="form-label">API Key / Token {editingId && '(Leave blank to keep unchanged)'}</label>
                        <input
                            type="password"
                            className="form-input"
                            value={newProvider.api_key}
                            onChange={e => setNewProvider({ ...newProvider, api_key: e.target.value })}
                            placeholder={editingId ? "********" : "sk_..."}
                        />
                    </div>
                    <div className="form-group" style={{ gridColumn: '1 / -1' }}>
                        <label className="form-label">Base URL (Public)</label>
                        <input
                            type="text"
                            className="form-input"
                            value={newProvider.base_url || ''}
                            onChange={e => setNewProvider({ ...newProvider, base_url: e.target.value })}
                            placeholder="https://myapp.ngrok.io"
                        />
                        <p className="text-xs text-slate-400 mt-1">Required for WebSocket connections. Can be set via BASE_URL env var.</p>
                    </div>
                    <div className="form-group" style={{ gridColumn: '1 / -1' }}>
                        <label className="form-label">From Number (Optional)</label>
                        <input
                            type="text"
                            className="form-input"
                            value={newProvider.from_number || ''}
                            onChange={e => setNewProvider({ ...newProvider, from_number: e.target.value })}
                            placeholder="+15550000000"
                        />
                    </div>
                    {newProvider.name === 'telnyx' && (
                        <div className="form-group" style={{ gridColumn: '1 / -1' }}>
                            <label className="form-label">App ID / Connection ID (Voice)</label>
                            <div className="flex gap-2">
                                <input
                                    type="text"
                                    className="form-input"
                                    value={newProvider.app_id || ''}
                                    onChange={e => setNewProvider({ ...newProvider, app_id: e.target.value })}
                                    placeholder="1234567890"
                                />
                                <button
                                    onClick={(e) => { e.preventDefault(); handleCreateApp(); }}
                                    className="btn btn-secondary"
                                    title="Create New App on Telnyx"
                                >
                                    <Plus size={18} /> Create App
                                </button>
                            </div>
                        </div>
                    )}
                    <div className="form-group" style={{ gridColumn: '1 / -1' }}>
                        <label className="form-label">Webhook Secret Token</label>
                        <div className="flex gap-2">
                            <input
                                type="text"
                                className="form-input"
                                value={newProvider.webhook_secret || 'Auto-generated on save'}
                                readOnly
                                style={{ backgroundColor: '#f1f5f9', color: '#64748b' }}
                            />
                            {editingId && (
                                <button
                                    onClick={(e) => {
                                        e.preventDefault();
                                        if (confirm("Regenerate webhook token? You will need to re-sync with Telnyx.")) {
                                            // Generate simple UUID-like string
                                            const newToken = Math.random().toString(36).substring(2, 15) + Math.random().toString(36).substring(2, 15);
                                            setNewProvider({ ...newProvider, webhook_secret: newToken });
                                        }
                                    }}
                                    className="btn btn-secondary"
                                    title="Regenerate Token"
                                >
                                    <RefreshCw size={18} />
                                </button>
                            )}
                        </div>
                        <p className="text-xs text-slate-400 mt-1">This token secures inbound webhooks. Use the "Sync" button in the list to update Telnyx.</p>
                    </div>

                    <div className="form-group" style={{ gridColumn: '1 / -1' }}>
                        <label className="checkbox-label mb-4">
                            <input
                                type="checkbox"
                                checked={newProvider.inbound_enabled !== false}
                                onChange={e => setNewProvider({ ...newProvider, inbound_enabled: e.target.checked })}
                            />
                            Enable Inbound Calls
                        </label>

                        <h3 className="text-sm font-semibold text-slate-300 mt-4 mb-2">Call Duration Limits</h3>
                        <div className="grid-2 mb-2">
                            <div className="form-group">
                                <label className="form-label">Max Duration (Seconds)</label>
                                <input
                                    type="number"
                                    className="form-input"
                                    value={newProvider.max_call_duration || ''}
                                    onChange={e => setNewProvider({ ...newProvider, max_call_duration: parseInt(e.target.value) })}
                                    placeholder="600"
                                />
                                <p className="text-xs text-slate-500 mt-1">Default: 600s (10 minutes)</p>
                            </div>
                            <div className="form-group">
                                <label className="form-label">Limit Message</label>
                                <input
                                    type="text"
                                    className="form-input"
                                    value={newProvider.call_limit_message || ''}
                                    onChange={e => setNewProvider({ ...newProvider, call_limit_message: e.target.value })}
                                    placeholder="This call has reached its time limit. Goodbye."
                                />
                                <p className="text-xs text-slate-500 mt-1">TTS message played before hangup.</p>
                            </div>
                        </div>
                        {newProvider.inbound_enabled !== false && (
                            <>
                                <label className="form-label">Inbound System Prompt (Optional)</label>
                                <textarea
                                    className="form-input"
                                    value={newProvider.inbound_system_prompt || ''}
                                    onChange={e => setNewProvider({ ...newProvider, inbound_system_prompt: e.target.value })}
                                    placeholder="You are a polite receptionist..."
                                    style={{ minHeight: '80px', resize: 'vertical' }}
                                />
                                <p className="text-xs text-slate-400 mt-1">Specific prompt for calls to this number.</p>
                            </>
                        )}
                    </div>
                </div>
                <div className="flex gap-2">
                    <button
                        onClick={handleSaveProvider}
                        disabled={loading}
                        className="btn btn-primary"
                    >
                        <Save size={18} />
                        {editingId ? 'Update Provider' : 'Save Provider'}
                    </button>
                    {editingId && (
                        <button
                            onClick={handleCancelEdit}
                            className="btn btn-secondary"
                        >
                            Cancel
                        </button>
                    )}
                </div>
            </div>

            {/* List */}
            <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
                <div style={{ padding: '1.5rem', borderBottom: '1px solid var(--border-color)' }}>
                    <h2 className="card-title" style={{ margin: 0 }}>Configured Providers</h2>
                </div>
                <div>
                    {providers.map(p => (
                        <div key={p.id} className="flex justify-between items-center" style={{ padding: '1rem 1.5rem', borderBottom: '1px solid rgba(51, 65, 85, 0.3)' }}>
                            <div className="flex items-center gap-4">
                                <div style={{ width: 8, height: 8, borderRadius: '50%', backgroundColor: p.enabled ? 'var(--accent-green)' : 'var(--text-secondary)' }} />
                                <div>
                                    <div style={{ fontWeight: 500, textTransform: 'capitalize' }}>{p.name}</div>
                                    <div style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>Priority: {p.priority} | From: {p.from_number || 'Default'} {p.app_id ? `| App ID: ${p.app_id} ` : ''}</div>
                                </div>
                            </div>

                            <div className="flex items-center gap-2">
                                {p.name === 'telnyx' && (
                                    <button
                                        onClick={() => handleSync(p)}
                                        className="btn btn-secondary"
                                        style={{ padding: '0.5rem' }}
                                        title="Sync Telnyx App Webhooks"
                                    >
                                        <RefreshCw size={20} />
                                    </button>
                                )}
                                <button
                                    onClick={() => handleEdit(p)}
                                    className="btn btn-secondary"
                                    style={{ padding: '0.5rem' }}
                                    title="Edit"
                                >
                                    Edit
                                </button>
                                <button
                                    onClick={() => handleToggle(p)}
                                    className="btn btn-icon"
                                    title={p.enabled ? "Disable" : "Enable"}
                                    style={{ color: p.enabled ? 'var(--accent-green)' : 'var(--text-secondary)' }}
                                >
                                    {p.enabled ? <CheckCircle size={20} /> : <XCircle size={20} />}
                                </button>
                                <button
                                    onClick={() => p.id && handleDelete(p.id)}
                                    className="btn btn-icon btn-icon-danger"
                                    title="Delete"
                                >
                                    <Trash2 size={20} />
                                </button>
                            </div>
                        </div>
                    ))}
                    {providers.length === 0 && (
                        <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-secondary)' }}>No providers configured yet.</div>
                    )}
                </div>
            </div>

            {/* Voice Config */}
            <div className="card">
                <h2 className="card-title">
                    Voice Configuration
                </h2>
                <p className="text-slate-400 mb-4 text-sm">Configure containers for Speech-to-Text (Parakeet) and Text-to-Speech (Chatterbox).</p>

                <div className="grid-2 mb-4">
                    <div className="form-group">
                        <label className="form-label">STT URL (Parakeet)</label>
                        <div className="flex gap-2">
                            <input
                                type="text"
                                className="form-input"
                                value={voiceConfig.stt_url}
                                onChange={e => setVoiceConfig({ ...voiceConfig, stt_url: e.target.value })}
                            />
                            <button
                                onClick={checkParakeet}
                                className="btn btn-secondary"
                                style={{ padding: '0 1rem' }}
                                title="Test Connection"
                            >
                                <CheckCircle size={18} />
                            </button>
                        </div>
                    </div>
                    <div className="form-group">
                        <label className="form-label">TTS URL (Chatterbox)</label>
                        <input
                            type="text"
                            className="form-input"
                            value={voiceConfig.tts_url}
                            onChange={e => setVoiceConfig({ ...voiceConfig, tts_url: e.target.value })}
                        />
                    </div>

                    <div className="form-group">
                        <label className="form-label">LLM Provider</label>
                        <select
                            className="form-select"
                            value={llmProvider}
                            onChange={e => handleProviderChange(e.target.value as any)}
                        >
                            <option value="custom">Custom URL</option>
                            <option value="openai">OpenAI</option>
                            <option value="ollama">Ollama</option>
                            <option value="openwebui">Open WebUI</option>
                        </select>
                    </div>

                    {llmProvider === 'custom' ? (
                        <div className="form-group">
                            <label className="form-label">LLM URL</label>
                            <input
                                type="text"
                                className="form-input"
                                value={voiceConfig.llm_url}
                                onChange={e => setVoiceConfig({ ...voiceConfig, llm_url: e.target.value })}
                                placeholder="http://open-webui:8080/v1"
                            />
                        </div>
                    ) : (
                        <>
                            {llmProvider !== 'openai' && (
                                <div className="form-group">
                                    <label className="form-label">Base URL / Domain</label>
                                    <input
                                        type="text"
                                        className="form-input"
                                        value={llmBaseDomain}
                                        onChange={e => handleBaseDomainChange(e.target.value)}
                                        placeholder={llmProvider === 'ollama' ? "http://localhost:11434" : "http://localhost:3000"}
                                    />
                                    <p className="text-xs text-slate-400 mt-1">We will append <code>/v1</code> automatically.</p>
                                </div>
                            )}
                            <div className="form-group">
                                <label className="form-label">Generated Endpoint</label>
                                <input
                                    type="text"
                                    className="form-input"
                                    value={voiceConfig.llm_url}
                                    disabled
                                    style={{ backgroundColor: '#f1f5f9', color: '#64748b' }}
                                />
                            </div>
                        </>
                    )}

                    <div className="form-group">
                        <label className="form-label">LLM API Key (Optional)</label>
                        <input
                            type="password"
                            className="form-input"
                            value={voiceConfig.llm_api_key || ''}
                            onChange={e => setVoiceConfig({ ...voiceConfig, llm_api_key: e.target.value })}
                        />
                    </div>
                    <div className="form-group">
                        <label className="form-label">LLM Model</label>
                        <div className="flex gap-2">
                            <input
                                type="text"
                                className="form-input"
                                value={voiceConfig.llm_model}
                                onChange={e => setVoiceConfig({ ...voiceConfig, llm_model: e.target.value })}
                                list="model-list"
                            />
                            <datalist id="model-list">
                                {availableModels.map(m => (
                                    <option key={m.id} value={m.id} />
                                ))}
                            </datalist>

                            <button
                                onClick={() => fetchModels(true)}
                                className="btn btn-secondary"
                                style={{ padding: '0 1rem' }}
                                title="Fetch Models"
                            >
                                <RefreshCw size={18} />
                            </button>
                        </div>
                    </div>

                    <div className="form-group" style={{ gridColumn: '1 / -1' }}>
                        <label className="form-label">System Prompt (Optional)</label>
                        <textarea
                            className="form-input"
                            value={voiceConfig.system_prompt || ''}
                            onChange={e => setVoiceConfig({ ...voiceConfig, system_prompt: e.target.value })}
                            placeholder={envDefaults.system_prompt || "You are a helpful assistant..."}
                            style={{ minHeight: '100px', resize: 'vertical' }}
                        />
                        <div className="flex justify-between items-center mt-2">
                            <p className="text-xs text-slate-400">
                                We will automatically append call control instructions (tools) to this prompt.
                            </p>
                            <label className="flex items-center gap-2 cursor-pointer">
                                <span className="text-sm font-medium text-slate-600">Send Conversation Context</span>
                                <input
                                    type="checkbox"
                                    checked={voiceConfig.send_conversation_context !== false}
                                    onChange={e => setVoiceConfig({ ...voiceConfig, send_conversation_context: e.target.checked })}
                                    className="scale-125"
                                />
                            </label>
                        </div>
                    </div>

                    <div className="form-group">
                        <label className="form-label">Voice ID</label>
                        <div className="flex gap-2">
                            <select
                                className="form-select"
                                value={voiceConfig.voice_id}
                                onChange={e => setVoiceConfig({ ...voiceConfig, voice_id: e.target.value })}
                            >
                                <option value="default">Default</option>
                                {voiceConfig.voice_id && voiceConfig.voice_id !== 'default' && !availableVoices.find(v => v.name === voiceConfig.voice_id) && (
                                    <option value={voiceConfig.voice_id}>{voiceConfig.voice_id} (Saved)</option>
                                )}
                                {availableVoices.map(v => (
                                    <option key={v.name} value={v.name}>{v.name} ({v.language})</option>
                                ))}
                            </select>
                            <button
                                onClick={() => fetchVoices(true)}
                                className="btn btn-secondary"
                                style={{ padding: '0 1rem' }}
                                title="Fetch Voices"
                            >
                                <RefreshCw size={18} />
                            </button>
                        </div>
                    </div>

                    <div className="form-group">
                        <label className="form-label">RTP Codec</label>
                        <select
                            className="form-select"
                            value={voiceConfig.rtp_codec || 'PCMU'}
                            onChange={e => setVoiceConfig({ ...voiceConfig, rtp_codec: e.target.value })}
                        >
                            <option value="PCMU">PCMU (u-law) - Default</option>
                            <option value="PCMA">PCMA (a-law)</option>
                            <option value="L16">L16 (8kHz Linear PCM) - High Quality</option>
                        </select>
                        <p className="text-xs text-slate-400 mt-1">
                            Audio encoding. PCMU/PCMA are compressed (8-bit). L16 is uncompressed (16-bit), providing clearer audio.
                        </p>
                    </div>

                    <div className="form-group">
                        <label className="form-label">STT Timeout (sec)</label>
                        <input
                            type="number"
                            className="form-input"
                            value={voiceConfig.stt_timeout || 10}
                            onChange={e => setVoiceConfig({ ...voiceConfig, stt_timeout: parseInt(e.target.value) || 10 })}
                        />
                    </div>
                    <div className="form-group">
                        <label className="form-label">TTS Timeout (sec)</label>
                        <input
                            type="number"
                            className="form-input"
                            value={voiceConfig.tts_timeout || 10}
                            onChange={e => setVoiceConfig({ ...voiceConfig, tts_timeout: parseInt(e.target.value) || 10 })}
                        />
                    </div>
                    <div className="form-group">
                        <label className="form-label">LLM Timeout (sec)</label>
                        <input
                            type="number"
                            className="form-input"
                            value={voiceConfig.llm_timeout || 10}
                            onChange={e => setVoiceConfig({ ...voiceConfig, llm_timeout: parseInt(e.target.value) || 10 })}
                        />
                    </div>
                </div>

                <button
                    onClick={handleSaveVoice}
                    disabled={voiceLoading}
                    className="btn btn-primary"
                >
                    <Save size={18} />
                    Save Voice Config
                </button>
            </div>

            {/* System Utilities */}
            <div className="card">
                <h2 className="card-title">System Utilities</h2>
                <div className="flex gap-4">
                    <button
                        onClick={async () => {
                            if (!confirm("Create/Update database tables?")) return;
                            try {
                                await axios.post('/api/admin/migrate');
                                alert("Database migrated successfully.");
                            } catch (e) {
                                alert("Migration failed.");
                            }
                        }}
                        className="btn btn-secondary"
                    >
                        Force Migrate Database
                    </button>
                </div>
            </div>
        </div >
    );
}
