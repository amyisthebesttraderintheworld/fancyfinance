import React, { useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

// AuthCallback handles the Telegram Login Widget OAuth flow if you ever
// point the widget's auth_url directly at /auth/callback instead of the
// backend webhook. Currently the backend handles this at /webhook/telegram-login
// and redirects to /dashboard/member?access=<token>, so this page is a
// fallback safety net — it just forwards to Dashboard if a token is present.

const TOKEN_KEY = 'fancyfinance_member_dashboard_token';

const AuthCallback = () => {
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const accessToken = params.get('access');

    if (accessToken) {
      // Backend already validated the Telegram HMAC and issued a token.
      localStorage.setItem(TOKEN_KEY, accessToken);
      navigate('/dashboard', { replace: true });
      return;
    }

    // No token — something went wrong upstream. Send back to login.
    navigate('/');
  }, []);

  return <div>Authenticating…</div>;
};

export default AuthCallback;
