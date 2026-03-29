import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

const TOKEN_KEY = 'fancyfinance_member_dashboard_token';
const COOKIE_KEY = 'fancyfinance_member_access';

const Dashboard = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const [token, setToken] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const accessToken = params.get('access');

    if (accessToken) {
      // Backend just sent us a fresh token — save it and clean the URL.
      localStorage.setItem(TOKEN_KEY, accessToken);
      setToken(accessToken);
      // Clean up the URL but stay on the dashboard
      navigate('/dashboard', { replace: true });
      return;
    }

    // No token in URL — check localStorage for an existing session.
    const storedToken = localStorage.getItem(TOKEN_KEY);
    if (storedToken) {
      setToken(storedToken);
    } else {
      // Last resort: check if the backend set the cookie (though JS might not see it if HttpOnly)
      // If we're here and have no token, the backend might have allowed us through
      // because of the cookie, so we can try to fetch data anyway or redirect.
      const hasCookie = document.cookie.includes(COOKIE_KEY);
      if (hasCookie) {
         // We'll let the component render and hope the backend data fetch works
         setToken('session-via-cookie');
      } else {
         // No token anywhere — send user back to the login page.
         window.location.href = '/dashboard/login';
      }
    }
  }, [location, navigate]);

  if (!token) {
    return <div>Loading...</div>;
  }

  return (
    <div>
      <h1>Member Dashboard</h1>
      {/* Dashboard content goes here */}
    </div>
  );
};

export default Dashboard;
