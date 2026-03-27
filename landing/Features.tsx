import { motion } from "framer-motion";
import {
  MessageCircle, Zap, BarChart3, PlayCircle, Radio,
  Shield, Database, LayoutDashboard, Settings,
} from "lucide-react";

const features = [
  { icon: MessageCircle, title: "Telegram-First Controls", desc: "Manage your entire trading workflow through bot commands." },
  { icon: Zap, title: "Fast Setup", desc: "From zero to backtesting in under five minutes." },
  { icon: BarChart3, title: "Backtesting", desc: "Test strategies against historical data for free." },
  { icon: PlayCircle, title: "Simulation Mode", desc: "Paper-trade with live market data, no real funds at risk." },
  { icon: Radio, title: "Live Trading", desc: "Execute real orders on Phemex through secure API connections." },
  { icon: Shield, title: "Secure API Key Storage", desc: "Encrypted credential storage in Supabase." },
  { icon: Database, title: "Persistent Account State", desc: "Positions, configs, and trade history are stored and queryable." },
  { icon: LayoutDashboard, title: "Dashboard Visibility", desc: "A web-based control center for monitoring and management." },
  { icon: Settings, title: "Operational Controls", desc: "Start, stop, and configure strategies without touching code." },
];

const Features = () => (
  <section className="py-24 lg:py-32 bg-secondary/30">
    <div className="section-container">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true }}
        className="text-center mb-16"
      >
        <h2 className="font-heading text-3xl sm:text-4xl font-bold mb-4">
          Built for <span className="text-gradient">serious traders</span>
        </h2>
        <p className="text-muted-foreground max-w-xl mx-auto text-lg">
          Every feature designed to give you control, visibility, and confidence.
        </p>
      </motion.div>

      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-6">
        {features.map((f, i) => (
          <motion.div
            key={f.title}
            initial={{ opacity: 0, y: 16 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ delay: i * 0.04, duration: 0.4 }}
            className="flex items-start gap-4 glass-card p-5"
          >
            <div className="w-9 h-9 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
              <f.icon className="w-4.5 h-4.5 text-primary" />
            </div>
            <div>
              <h3 className="font-heading font-semibold mb-1">{f.title}</h3>
              <p className="text-sm text-muted-foreground leading-relaxed">{f.desc}</p>
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  </section>
);

export default Features;
