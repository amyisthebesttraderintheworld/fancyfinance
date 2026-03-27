import { Github } from "lucide-react";

const GITHUB_URL = "https://github.com/amyisthebesttraderintheworld/fancyfinance";
const DASHBOARD_URL = "/dashboard";
const LOGO_URL = "/dashboard/assets/logo.png";

const Footer = () => (
  <footer className="border-t border-border py-12">
    <div className="section-container">
      <div className="flex flex-col md:flex-row items-center justify-between gap-6">
        <div>
          <img src={LOGO_URL} alt="FancyFinance" className="h-8 w-auto" />
          <p className="text-xs text-muted-foreground mt-1">
            Educational trading software. Not financial advice.
          </p>
        </div>
        <div className="flex items-center gap-4">
          <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer" className="text-muted-foreground hover:text-foreground transition-colors">
            <Github className="w-4 h-4" />
          </a>
          <a href={DASHBOARD_URL} className="text-xs text-muted-foreground hover:text-foreground transition-colors">
            Dashboard
          </a>
          <a href="/privacy-policy" className="text-xs text-muted-foreground hover:text-foreground transition-colors">
            Privacy
          </a>
          <a href="/terms-of-use" className="text-xs text-muted-foreground hover:text-foreground transition-colors">
            Terms
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
