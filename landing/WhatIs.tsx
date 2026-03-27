import { motion } from "framer-motion";
import { Bot, Server, Shield, BarChart3 } from "lucide-react";

const pillars = [
  { icon: Bot, title: "Telegram Control", desc: "Manage every aspect of your trading workflow through intuitive bot commands." },
  { icon: Server, title: "Backend Automation", desc: "A Railway-hosted Python backend handles execution, scheduling, and state management." },
  { icon: Shield, title: "Secure Storage", desc: "Exchange API keys and account data are encrypted and stored in Supabase." },
  { icon: BarChart3, title: "Real-Time Monitoring", desc: "Track positions, P&L, and system status through Telegram alerts and a web dashboard." },
];

const fadeUp = {
  hidden: { opacity: 0, y: 24 },
  visible: (i: number) => ({ opacity: 1, y: 0, transition: { delay: i * 0.1, duration: 0.5 } }),
};

const WhatIs = () => (
  <section className="py-24 lg:py-32">
    <div className="section-container">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true }}
        transition={{ duration: 0.5 }}
        className="text-center mb-16"
      >
        <h2 className="font-heading text-3xl sm:text-4xl font-bold mb-4">
          What is <span className="text-gradient">FancyFinance</span>?
        </h2>
        <p className="text-muted-foreground max-w-2xl mx-auto text-lg">
          A Telegram-first algorithmic trading platform that combines bot-driven
          controls with automated backend infrastructure, so you can backtest,
          simulate, and trade — all from one interface.
        </p>
      </motion.div>

      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-6">
        {pillars.map((p, i) => (
          <motion.div
            key={p.title}
            custom={i}
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true }}
            variants={fadeUp}
            className="glass-card p-6 group hover:border-primary/30 transition-colors"
          >
            <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center mb-4 group-hover:bg-primary/20 transition-colors">
              <p.icon className="w-5 h-5 text-primary" />
            </div>
            <h3 className="font-heading font-semibold text-lg mb-2">{p.title}</h3>
            <p className="text-sm text-muted-foreground leading-relaxed">{p.desc}</p>
          </motion.div>
        ))}
      </div>
    </div>
  </section>
);

export default WhatIs;
