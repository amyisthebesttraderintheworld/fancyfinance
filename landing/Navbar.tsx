import { Button } from "@/components/ui/button";
import { ArrowRight, Github, LayoutDashboard } from "lucide-react";
import logo from "@/assets/logo.png";

const GITHUB_URL = "https://github.com/amyisthebesttraderintheworld/fancyfinance";
const DASHBOARD_URL = "https://fancyfinance-production.up.railway.app";

const TELEGRAM_URL = "https://t.me/FancyFinanceBot";

const Navbar = () => (
  <nav className="fixed top-0 left-0 right-0 z-50 border-b border-border/50 bg-background/80 backdrop-blur-xl">
    <div className="section-container flex items-center justify-between h-16">
      <a href="/" className="flex items-center">
        <img src={logo} alt="FancyFinance" className="h-10 w-auto" />
      </a>

      <div className="hidden md:flex items-center gap-8 text-sm text-muted-foreground">
        <a href="#how-it-works" className="hover:text-foreground transition-colors">How It Works</a>
        <a href="#plans" className="hover:text-foreground transition-colors">Pricing</a>
      </div>

      <div className="flex items-center gap-2">
        <Button variant="ghost" size="icon" asChild>
          <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer" aria-label="GitHub">
            <Github className="w-4 h-4" />
          </a>
        </Button>
        <Button variant="heroOutline" size="sm" asChild>
          <a href={DASHBOARD_URL} target="_blank" rel="noopener noreferrer">
            <LayoutDashboard className="w-3.5 h-3.5 mr-1" />
            Dashboard
          </a>
        </Button>
        <Button variant="hero" size="sm" asChild>
          <a href={TELEGRAM_URL} target="_blank" rel="noopener noreferrer">
            Start Trading
            <ArrowRight className="w-3.5 h-3.5 ml-1" />
          </a>
        </Button>
      </div>
    </div>
  </nav>
);

export default Navbar;
