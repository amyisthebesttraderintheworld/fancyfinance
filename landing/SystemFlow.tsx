import { motion } from "framer-motion";
import { ArrowDown } from "lucide-react";

const flow = [
  "Visit marketing site",
  "Click through to Telegram bot",
  "Start onboarding & review disclosure",
  "Verify email address",
  "Free tier: backtesting access",
  "Start 7-day free trial, then $6.99/mo via Stripe",
  "Store exchange API keys",
  "Run simulation or live trading",
  "Monitor via Telegram & dashboard",
];

const SystemFlow = () => (
  <section className="py-24 lg:py-32">
    <div className="section-container">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true }}
        className="text-center mb-16"
      >
        <h2 className="font-heading text-3xl sm:text-4xl font-bold mb-4">
          The user <span className="text-gradient">journey</span>
        </h2>
        <p className="text-muted-foreground max-w-xl mx-auto text-lg">
          From curiosity to live monitoring in one continuous flow.
        </p>
      </motion.div>

      <div className="max-w-md mx-auto">
        {flow.map((step, i) => (
          <motion.div
            key={step}
            initial={{ opacity: 0, y: 12 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ delay: i * 0.06 }}
            className="flex flex-col items-center"
          >
            <div className="glass-card px-6 py-4 w-full text-center">
              <span className="text-xs text-primary font-semibold mr-2">{String(i + 1).padStart(2, "0")}</span>
              <span className="text-sm font-medium">{step}</span>
            </div>
            {i < flow.length - 1 && (
              <ArrowDown className="w-4 h-4 text-primary/40 my-2" />
            )}
          </motion.div>
        ))}
      </div>
    </div>
  </section>
);

export default SystemFlow;
