import { motion } from "framer-motion";
import { Button } from "@/components/ui/button";
import { Check, ArrowRight, Loader2 } from "lucide-react";
import { useState } from "react";
import { supabase } from "@/integrations/supabase/client";
import { toast } from "sonner";

const TELEGRAM_URL = "https://t.me/FancyFinanceBot";

const plans = [
  {
    name: "Free",
    price: "$0",
    period: "forever",
    features: ["Backtesting", "Telegram onboarding", "Email verification", "Account creation"],
    cta: "Get Started",
    highlighted: false,
  },
  {
    name: "Pro",
    price: "$6.99",
    period: "/month",
    trial: "7-day free trial",
    features: [
      "Everything in Free",
      "7-day free trial included",
      "Simulation mode",
      "Live trading mode",
      "Secure API key storage",
      "Dashboard access",
      "Operational controls",
    ],
    cta: "Start Free Trial",
    highlighted: true,
  },
];

const Plans = () => {
  const [loading, setLoading] = useState(false);

  const handleUpgrade = async () => {
    setLoading(true);
    try {
      const { data, error } = await supabase.functions.invoke("create-checkout");
      if (error) throw error;
      if (data?.url) {
        window.open(data.url, "_blank");
      }
    } catch (err: any) {
      console.error(err);
      toast.error("Could not start checkout. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <section id="plans" className="py-24 lg:py-32">
      <div className="section-container">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          className="text-center mb-16"
        >
          <h2 className="font-heading text-3xl sm:text-4xl font-bold mb-4">
            Simple, transparent <span className="text-gradient">pricing</span>
          </h2>
          <p className="text-muted-foreground max-w-xl mx-auto text-lg">
            Start free. Upgrade when you're ready for simulation and live trading.
          </p>
        </motion.div>

        <div className="grid md:grid-cols-2 gap-8 max-w-3xl mx-auto">
          {plans.map((plan, i) => (
            <motion.div
              key={plan.name}
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ delay: i * 0.1 }}
              className={`glass-card p-8 flex flex-col ${
                plan.highlighted ? "border-primary/40 shadow-lg shadow-primary/5" : ""
              }`}
            >
              {plan.highlighted && (
                <span className="text-xs font-semibold text-primary bg-primary/10 rounded-full px-3 py-1 self-start mb-4">
                  Most Popular
                </span>
              )}
              <h3 className="font-heading text-2xl font-bold mb-1">{plan.name}</h3>
              <div className="flex items-baseline gap-1 mb-2">
                <span className="font-heading text-4xl font-bold">{plan.price}</span>
                <span className="text-muted-foreground text-sm">{plan.period}</span>
              </div>
              {plan.trial && (
                <p className="text-sm font-medium text-primary mb-6">{plan.trial}</p>
              )}
              {!plan.trial && <div className="mb-4" />}
              <ul className="space-y-3 mb-8 flex-1">
                {plan.features.map((f) => (
                  <li key={f} className="flex items-start gap-2 text-sm text-secondary-foreground">
                    <Check className="w-4 h-4 text-primary mt-0.5 shrink-0" />
                    {f}
                  </li>
                ))}
              </ul>
              {plan.highlighted ? (
                <div className="space-y-3">
                  <Button
                    variant="hero"
                    size="lg"
                    className="w-full text-lg h-14 shadow-xl shadow-primary/30"
                    onClick={handleUpgrade}
                    disabled={loading}
                  >
                    {loading ? (
                      <>
                        <Loader2 className="w-5 h-5 mr-1 animate-spin" />
                        Loading…
                      </>
                    ) : (
                      <>
                        🚀 Start Your 7-Day Free Trial
                        <ArrowRight className="w-5 h-5 ml-1" />
                      </>
                    )}
                  </Button>
                  <p className="text-center text-xs text-muted-foreground">
                    No charge for 7 days · Cancel anytime
                  </p>
                </div>
              ) : (
                <Button variant="heroOutline" size="lg" className="w-full" asChild>
                  <a href={TELEGRAM_URL} target="_blank" rel="noopener noreferrer">
                    {plan.cta}
                    <ArrowRight className="w-4 h-4 ml-1" />
                  </a>
                </Button>
              )}
            </motion.div>
          ))}
        </div>

        <p className="text-center text-xs text-muted-foreground mt-8">
          Pro subscriptions include a 7-day free trial. Billed through Stripe. Cancel anytime.
        </p>
      </div>
    </section>
  );
};

export default Plans;
