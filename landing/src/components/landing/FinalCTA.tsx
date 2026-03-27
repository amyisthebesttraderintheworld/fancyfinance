import { motion } from "framer-motion";
import { Button } from "@/components/ui/button";
import { ArrowRight } from "lucide-react";

const TELEGRAM_URL = "https://t.me/FancyFinanceBot";

const FinalCTA = () => (
  <section className="py-24 lg:py-32 relative overflow-hidden">
    <div className="absolute inset-0 bg-primary/[0.03]" />
    <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[500px] h-[500px] rounded-full bg-primary/5 blur-[100px] pointer-events-none" />

    <motion.div
      initial={{ opacity: 0, y: 20 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true }}
      className="section-container relative text-center"
    >
      <h2 className="font-heading text-3xl sm:text-4xl lg:text-5xl font-bold mb-6">
        Ready to start <span className="text-gradient">trading smarter</span>?
      </h2>
      <p className="text-muted-foreground text-lg max-w-xl mx-auto mb-10">
        Open the Telegram bot, create your account, and run your first backtest
        in minutes — completely free.
      </p>
      <Button variant="hero" size="lg" asChild>
        <a href={TELEGRAM_URL} target="_blank" rel="noopener noreferrer">
          Open FancyFinance on Telegram
          <ArrowRight className="w-4 h-4 ml-1" />
        </a>
      </Button>
    </motion.div>
  </section>
);

export default FinalCTA;
