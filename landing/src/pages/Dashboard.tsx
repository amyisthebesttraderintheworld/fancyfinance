import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

const TOKEN_KEY = 'fancyfinance_member_dashboard_token';

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
      navigate('/dashboard/member', { replace: true });
      return;
    }

    // No token in URL — check localStorage for an existing session.
    const storedToken = localStorage.getItem(TOKEN_KEY);
    if (storedToken) {
      setToken(storedToken);
    } else {
      // No token anywhere — send user back to the login page.
      navigate('/');
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
