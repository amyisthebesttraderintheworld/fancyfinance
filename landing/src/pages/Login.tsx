import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';

const Login = () => {
  const navigate = useNavigate();
  const { user } = useAuth();
  const widgetRef = useRef<HTMLDivElement>(null);
  const [telegramConfig, setTelegramConfig] = useState<{ enabled: boolean, bot_username: string, auth_url: string } | null>(null);

  useEffect(() => {
    // Fetch bootstrap config to get the correct bot username and auth endpoint
    fetch('/dashboard/bootstrap')
      .then(res => res.json())
      .then(data => {
        if (data.telegram_login) {
          setTelegramConfig(data.telegram_login);
        }
      })
      .catch(err => console.error("Failed to fetch bootstrap config:", err));
  }, []);

  useEffect(() => {
    // If user is already authenticated, go to dashboard
    if (user) {
      navigate('/dashboard', { replace: true });
    }
  }, [user, navigate]);

  useEffect(() => {
    if (!telegramConfig || !telegramConfig.enabled || !telegramConfig.bot_username) return;

    // The AUTH_URL must point to the BACKEND verification endpoint.
    // The backend then validates the Telegram HMAC and redirects back to /dashboard?access=TOKEN
    const AUTH_URL = window.location.origin + (telegramConfig.auth_url || "/dashboard/login/telegram");

    if (widgetRef.current && !widgetRef.current.innerHTML) {
      console.log("Injecting Telegram Widget with Auth URL:", AUTH_URL);
      const script = document.createElement("script");
      script.async = true;
      script.src = "https://telegram.org/js/telegram-widget.js?22";
      script.setAttribute("data-telegram-login", telegramConfig.bot_username);
      script.setAttribute("data-size", "large");
      script.setAttribute("data-radius", "12");
      script.setAttribute("data-userpic", "false");
      script.setAttribute("data-auth-url", AUTH_URL);
      widgetRef.current.appendChild(script);
    }
  }, [telegramConfig]);

  return (
    <div className="flex flex-col items-center justify-center min-h-screen bg-slate-950 text-white p-4">
      <div className="w-full max-w-md p-8 bg-slate-900 border border-slate-800 rounded-3xl shadow-2xl text-center">
        <h1 className="text-3xl font-bold mb-2">Welcome Back</h1>
        <p className="text-slate-400 mb-8">Sign in with Telegram to access your trading dashboard.</p>
        
        <div className="flex justify-center mb-8" ref={widgetRef}>
          {!telegramConfig && <div className="animate-pulse text-slate-500">Loading Login...</div>}
          {telegramConfig && !telegramConfig.enabled && (
            <div className="text-amber-500 text-sm">
              Telegram Login is not configured. 
              Please check your TELEGRAM_BOT_TOKEN.
            </div>
          )}
        </div>
        
        <div className="text-xs text-slate-500 uppercase tracking-widest mt-4">
          FancyFinance Member Portal
        </div>
      </div>
      
      <button 
        onClick={() => navigate('/')}
        className="mt-8 text-slate-400 hover:text-white transition-colors text-sm"
      >
        ← Back to Home
      </button>
    </div>
  );
};

export default Login;
