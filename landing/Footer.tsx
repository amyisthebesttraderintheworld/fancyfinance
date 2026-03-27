import { Github } from "lucide-react";
import logo from "@/assets/logo.png";

const GITHUB_URL = "https://github.com/amyisthebesttraderintheworld/fancyfinance";
const DASHBOARD_URL = "https://fancyfinance-production.up.railway.app";

const Footer = () => (
  <footer className="border-t border-border py-12">
    <div className="section-container">
      <div className="flex flex-col md:flex-row items-center justify-between gap-6">
        <div>
          <img src={logo} alt="FancyFinance" className="h-8 w-auto" />
          <p className="text-xs text-muted-foreground mt-1">
            Educational trading software. Not financial advice.
          </p>
        </div>
        <div className="flex items-center gap-4">
          <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer" className="text-muted-foreground hover:text-foreground transition-colors">
            <Github className="w-4 h-4" />
          </a>
          <a href={DASHBOARD_URL} target="_blank" rel="noopener noreferrer" className="text-xs text-muted-foreground hover:text-foreground transition-colors">
            Dashboard
          </a>
          <a href="/privacy-policy.html" className="text-xs text-muted-foreground hover:text-foreground transition-colors">
            Privacy Policy
          </a>
          <a href="/terms-of-use.html" className="text-xs text-muted-foreground hover:text-foreground transition-colors">
            Terms of Use
          </a>
        </div>
        <p className="text-xs text-muted-foreground">
          &copy; {new Date().getFullYear()} FancyFinance. All rights reserved.
        </p>
      </div>
    </div>
  </footer>
);

export default Footer;
