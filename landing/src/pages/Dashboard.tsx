import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';

const Dashboard = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, loading, logout } = useAuth();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const accessToken = params.get('access');

    if (accessToken) {
      console.log("Captured access token from URL");
      // The actual saving is done in AuthContext if we use that for persistence,
      // but let's be explicit here to ensure it works.
      localStorage.setItem('fancyfinance_member_dashboard_token', accessToken);
      
      // Clean up the URL but stay on /dashboard
      navigate('/dashboard', { replace: true });
      
      // Force a page reload to re-initialize the AuthContext with the new token
      window.location.reload();
      return;
    }

    if (!loading && !user) {
      console.log("No user session found, redirecting to home");
      // If we're not loading and no user is found, send them home
      // (or to a specific login page if you prefer)
      navigate('/', { replace: true });
    }
  }, [location, navigate, user, loading]);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-slate-950 text-white">
        <div className="text-xl animate-pulse">Initializing Session...</div>
      </div>
    );
  }

  if (!user) {
    return null; // Will redirect in useEffect
  }

  return (
    <div className="min-h-screen bg-slate-950 text-white p-8">
      <div className="max-w-4xl mx-auto">
        <header className="flex justify-between items-center mb-12 border-b border-slate-800 pb-6">
          <div>
            <h1 className="text-3xl font-bold bg-gradient-to-r from-blue-400 to-emerald-400 bg-clip-text text-transparent">
              Member Dashboard
            </h1>
            <p className="text-slate-400 mt-1">Welcome back to FancyFinance</p>
          </div>
          <button 
            onClick={() => {
              logout();
              navigate('/');
            }}
            className="px-4 py-2 bg-slate-800 hover:bg-slate-700 rounded-lg transition-colors text-sm font-medium"
          >
            Sign Out
          </button>
        </header>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="bg-slate-900/50 border border-slate-800 p-6 rounded-2xl">
            <h2 className="text-lg font-semibold mb-4 text-blue-400">Account Status</h2>
            <div className="space-y-3">
              <div className="flex justify-between">
                <span className="text-slate-500 text-sm">Session Type:</span>
                <span className="text-sm font-mono text-emerald-400">Authenticated Member</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500 text-sm">Live Access:</span>
                <span className="text-sm text-emerald-500">Enabled</span>
              </div>
            </div>
          </div>

          <div className="bg-slate-900/50 border border-slate-800 p-6 rounded-2xl">
            <h2 className="text-lg font-semibold mb-4 text-emerald-400">Trading Activity</h2>
            <p className="text-sm text-slate-500 italic">No recent trades to display in this prototype view.</p>
          </div>
        </div>

        <div className="mt-12 p-12 text-center border-2 border-dashed border-slate-800 rounded-3xl">
          <p className="text-slate-500">Real-time data visualization and strategy controls are currently under construction.</p>
          <p className="text-slate-600 text-xs mt-2 uppercase tracking-widest">FancyFinance v2.0-Alpha</p>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
