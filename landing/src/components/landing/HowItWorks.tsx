import { motion } from "framer-motion";

const steps = [
  { num: "01", title: "Open the Telegram Bot", desc: "Find @FancyFinanceBot on Telegram and tap Start." },
  { num: "02", title: "Review Disclosure & Create Account", desc: "Read the risk disclosure and educational disclaimer, then create your account." },
  { num: "03", title: "Verify Your Email", desc: "Receive a verification code via n8n-powered email delivery and confirm your address." },
  { num: "04", title: "Choose Your Plan", desc: "Start with free backtesting or upgrade to Pro for simulation and live trading." },
  { num: "05", title: "Upgrade via Stripe", desc: "Start with a 7-day free trial, then $6.99/month through Stripe's secure checkout." },
  { num: "06", title: "Store Exchange API Keys", desc: "Securely store your Phemex API credentials for automated order execution." },
  { num: "07", title: "Run Simulation or Live", desc: "Test strategies in simulation mode, then switch to live when you're ready." },
  { num: "08", title: "Monitor Everything", desc: "Use Telegram commands and the web dashboard to track positions and system status." },
];

const HowItWorks = () => (
  <section id="how-it-works" className="py-24 lg:py-32 bg-secondary/30">
    <div className="section-container">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true }}
        className="text-center mb-16"
      >
        <h2 className="font-heading text-3xl sm:text-4xl font-bold mb-4">
          How It <span className="text-gradient">Works</span>
        </h2>
        <p className="text-muted-foreground max-w-xl mx-auto text-lg">
          From first click to live monitoring in eight steps.
        </p>
      </motion.div>

      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-6">
        {steps.map((s, i) => (
          <motion.div
            key={s.num}
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ delay: i * 0.05, duration: 0.4 }}
            className="glass-card p-6 relative"
          >
            <span className="text-5xl font-heading font-bold text-primary/10 absolute top-4 right-4">
              {s.num}
            </span>
            <h3 className="font-heading font-semibold mb-2 pr-12">{s.title}</h3>
            <p className="text-sm text-muted-foreground leading-relaxed">{s.desc}</p>
          </motion.div>
        ))}
      </div>
    </div>
  </section>
);

export default HowItWorks;
