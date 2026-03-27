import { motion } from "framer-motion";

const layers = [
  { label: "Marketing Site", desc: "This website — explains the product and sends users to Telegram.", color: "bg-primary/10 border-primary/20" },
  { label: "Telegram Bot", desc: "User-facing interface for onboarding, commands, and notifications.", color: "bg-primary/15 border-primary/25" },
  { label: "Railway Backend", desc: "Python service handling strategy execution, scheduling, and state.", color: "bg-primary/10 border-primary/20" },
  { label: "FastAPI Control Layer", desc: "API plane for managing workflows, users, and system operations.", color: "bg-primary/15 border-primary/25" },
  { label: "Supabase", desc: "Persistent storage for users, configs, positions, and trade history.", color: "bg-primary/10 border-primary/20" },
  { label: "Stripe Billing", desc: "Handles Pro subscription payments and membership gating.", color: "bg-primary/15 border-primary/25" },
  { label: "n8n Email Verification", desc: "Automated email delivery for account verification codes.", color: "bg-primary/10 border-primary/20" },
  { label: "Exchange Connectivity", desc: "Secure API integration with Phemex for order execution.", color: "bg-primary/15 border-primary/25" },
];

const Architecture = () => (
  <section className="py-24 lg:py-32 bg-secondary/30">
    <div className="section-container">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true }}
        className="text-center mb-16"
      >
        <h2 className="font-heading text-3xl sm:text-4xl font-bold mb-4">
          Architecture <span className="text-gradient">overview</span>
        </h2>
        <p className="text-muted-foreground max-w-xl mx-auto text-lg">
          A purpose-built stack for algorithmic trading at every layer.
        </p>
      </motion.div>

      <div className="max-w-2xl mx-auto space-y-3">
        {layers.map((l, i) => (
          <motion.div
            key={l.label}
            initial={{ opacity: 0, x: -20 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true }}
            transition={{ delay: i * 0.06, duration: 0.4 }}
            className={`flex items-start gap-4 rounded-xl border p-5 ${l.color}`}
          >
            <div className="w-2 h-2 rounded-full bg-primary mt-2 shrink-0" />
            <div>
              <h3 className="font-heading font-semibold mb-0.5">{l.label}</h3>
              <p className="text-sm text-muted-foreground">{l.desc}</p>
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  </section>
);

export default Architecture;
