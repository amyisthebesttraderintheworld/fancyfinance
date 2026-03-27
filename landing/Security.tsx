import { motion } from "framer-motion";
import { AlertTriangle, Eye, KeyRound, CreditCard, BookOpen, ShieldCheck } from "lucide-react";

const points = [
  { icon: BookOpen, title: "Educational Software Only", desc: "FancyFinance is a trading tool — not financial advice. All decisions are yours." },
  { icon: AlertTriangle, title: "No Guaranteed Profits", desc: "Live trading carries real risk. Past performance does not predict future results." },
  { icon: KeyRound, title: "You Control Your Keys", desc: "Exchange credentials are yours. FancyFinance stores them securely but never has withdrawal access." },
  { icon: Eye, title: "Transparent Risk Disclosure", desc: "Every user reviews a clear risk disclaimer before account creation." },
  { icon: ShieldCheck, title: "Secure Data Handling", desc: "Account data is encrypted and stored in Supabase with row-level security." },
  { icon: CreditCard, title: "Stripe-Powered Billing", desc: "Subscription payments are handled entirely by Stripe. We never see your card details." },
];

const Security = () => (
  <section className="py-24 lg:py-32">
    <div className="section-container">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true }}
        className="text-center mb-16"
      >
        <h2 className="font-heading text-3xl sm:text-4xl font-bold mb-4">
          Security, trust &amp; <span className="text-gradient">risk transparency</span>
        </h2>
        <p className="text-muted-foreground max-w-2xl mx-auto text-lg">
          We believe credibility comes from honesty. Here's what you should know.
        </p>
      </motion.div>

      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-6">
        {points.map((p, i) => (
          <motion.div
            key={p.title}
            initial={{ opacity: 0, y: 16 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ delay: i * 0.05, duration: 0.4 }}
            className="glass-card p-6"
          >
            <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center mb-4">
              <p.icon className="w-5 h-5 text-primary" />
            </div>
            <h3 className="font-heading font-semibold mb-2">{p.title}</h3>
            <p className="text-sm text-muted-foreground leading-relaxed">{p.desc}</p>
          </motion.div>
        ))}
      </div>
    </div>
  </section>
);

export default Security;
