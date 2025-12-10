import { Routes, Route, Link } from 'react-router-dom';
import Dashboard from './pages/Dashboard';
import Settings from './pages/Settings';
import MessageLogs from './pages/MessageLogs';
import { LayoutDashboard, Settings as SettingsIcon, List } from 'lucide-react';

function App() {
    return (
        <div className="app-container">
            <nav className="navbar">
                <div className="nav-brand">
                    <span>LLM Communications Gateway</span>
                </div>
                <div className="nav-links">
                    <Link to="/" className="nav-link">
                        <LayoutDashboard size={18} />
                        Dashboard
                    </Link>
                    <Link to="/logs" className="nav-link">
                        <List size={18} />
                        Logs
                    </Link>
                    <Link to="/settings" className="nav-link">
                        <SettingsIcon size={18} />
                        Settings
                    </Link>
                </div>
            </nav>

            <main className="main-content">
                <Routes>
                    <Route path="/" element={<Dashboard />} />
                    <Route path="/logs" element={<MessageLogs />} />
                    <Route path="/settings" element={<Settings />} />
                </Routes>
            </main>
        </div>
    );
}

export default App;
