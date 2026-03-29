import { useEffect, useState, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';

const TOKEN_KEY = 'fancyfinance_member_dashboard_token';

const Dashboard = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, loading, logout, refresh } = useAuth();
  const [tokenFoundInUrl, setTokenFoundInUrl] = useState(false);
  const isRefreshingRef = useRef(false);

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const accessToken = params.get('access');

    if (accessToken) {
      console.log("Captured access token from URL at /dashboard");
      localStorage.setItem(TOKEN_KEY, accessToken);
      setTokenFoundInUrl(true);
      
      // Navigate to clean URL
      navigate('/dashboard', { replace: true });
      
      // Trigger a refresh of the AuthContext to recognize the new token
      if (!isRefreshingRef.current) {
        isRefreshingRef.current = true;
        refresh();
      }
      return;
    }

    if (!loading && !user && !tokenFoundInUrl) {
      const storedToken = localStorage.getItem(TOKEN_KEY);
      if (!storedToken) {
        console.log("No user session found, redirecting to login");
        navigate('/dashboard/login', { replace: true });
      }
    }
  }, [location, navigate, user, loading, refresh, tokenFoundInUrl]);

  if (loading || (!user && !tokenFoundInUrl)) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-slate-950 text-white gap-4">
        <div className="text-xl animate-pulse font-medium text-slate-400">Synchronizing Session...</div>
        <div className="w-64 h-1 bg-slate-900 rounded-full overflow-hidden">
           <div className="h-full bg-blue-500 animate-[loading_2s_ease-in-out_infinite]"></div>
        </div>
        <style>{`
          @keyframes loading {
            0% { width: 0%; transform: translateX(-100%); }
            50% { width: 50%; }
            100% { width: 100%; transform: translateX(200%); }
          }
        `}</style>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-950 text-white p-8 selection:bg-blue-500/30">
      <div className="max-w-4xl mx-auto">
        <header className="flex justify-between items-center mb-12 border-b border-slate-800 pb-6">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-blue-600 rounded-xl flex items-center justify-center shadow-lg shadow-blue-900/20">
              <span className="font-bold text-xl">F</span>
            </div>
            <div>
              <h1 className="text-3xl font-bold bg-gradient-to-r from-blue-400 to-emerald-400 bg-clip-text text-transparent">
                Member Dashboard
              </h1>
              <p className="text-slate-400 text-xs font-medium tracking-wide uppercase mt-0.5">Algorithmic Trading Terminal</p>
            </div>
          </div>
          <button 
            onClick={() => {
              logout();
              navigate('/dashboard/login');
            }}
            className="px-4 py-2 bg-slate-900 hover:bg-slate-800 border border-slate-800 hover:border-slate-700 rounded-xl transition-all text-xs font-bold uppercase tracking-widest text-slate-400 hover:text-white"
          >
            Sign Out
          </button>
        </header>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="bg-slate-900/40 backdrop-blur-xl border border-slate-800/50 p-6 rounded-3xl shadow-2xl relative overflow-hidden group">
            <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity">
               <svg className="w-20 h-20 text-blue-400" fill="currentColor" viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8zm4.59-12.42L10 14.17l-2.59-2.58L6 13l4 4 8-8z"/></svg>
            </div>
            <h2 className="text-sm font-bold mb-6 text-slate-500 uppercase tracking-widest">Connectivity Status</h2>
            <div className="space-y-4">
              <div className="flex justify-between items-center">
                <span className="text-slate-400 text-sm">Session Layer:</span>
                <span className="text-[10px] font-bold font-mono text-emerald-400 px-2 py-0.5 bg-emerald-400/5 rounded border border-emerald-400/20 uppercase">Encrypted</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-400 text-sm">Execution Node:</span>
                <span className="text-[10px] font-bold font-mono text-blue-400 px-2 py-0.5 bg-blue-400/5 rounded border border-blue-400/20 uppercase">Phemex Simulation</span>
              </div>
            </div>
          </div>

          <div className="bg-slate-900/40 backdrop-blur-xl border border-slate-800/50 p-6 rounded-3xl shadow-2xl relative overflow-hidden group">
            <h2 className="text-sm font-bold mb-6 text-slate-500 uppercase tracking-widest">Market Intelligence</h2>
            <div className="flex flex-col items-center justify-center h-20 border border-slate-800/50 rounded-2xl bg-slate-950/30 gap-2">
               <div className="flex gap-1.5">
                 <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></div>
                 <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse delay-75"></div>
                 <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse delay-150"></div>
               </div>
               <span className="text-slate-600 text-[10px] font-bold uppercase tracking-widest">Awaiting Live Feed...</span>
            </div>
          </div>
        </div>

        <div className="mt-12 p-16 text-center border-2 border-dashed border-slate-800/50 rounded-[2.5rem] bg-slate-900/10">
          <h3 className="text-slate-400 font-bold text-lg mb-2">Interface Initialized</h3>
          <p className="text-slate-500 text-sm max-w-sm mx-auto leading-relaxed">Your secure session is active. Strategy engine and visualizers are currently synchronizing with the production node.</p>
          <p className="text-slate-700 text-[10px] mt-12 font-black uppercase tracking-[0.4em]">FancyFinance // Codex 2.1-Alpha</p>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
