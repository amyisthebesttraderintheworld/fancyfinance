import { motion } from "framer-motion";
import { Button } from "@/components/ui/button";
import { ArrowRight, MessageCircle } from "lucide-react";

const TELEGRAM_URL = "https://t.me/FancyFinanceBot";

const Hero = () => (
  <section className="relative min-h-[90vh] flex items-center overflow-hidden">
    {/* Ambient glow */}
    <div className="absolute top-1/3 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] rounded-full bg-primary/5 blur-[120px] pointer-events-none" />

    <div className="section-container w-full py-24 lg:py-32">
      <motion.div
        initial={{ opacity: 0, y: 30 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.7, ease: "easeOut" }}
        className="max-w-3xl mx-auto text-center"
      >
        <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full border-glow bg-secondary/50 text-sm text-muted-foreground mb-8">
          <MessageCircle className="w-4 h-4 text-primary" />
          Telegram-first algorithmic trading
        </div>

        <h1 className="font-heading text-4xl sm:text-5xl lg:text-6xl font-bold tracking-tight leading-[1.1] mb-6">
          Algorithmic trading,{" "}
          <span className="text-gradient">controlled from Telegram</span>
        </h1>

        <p className="text-lg sm:text-xl text-muted-foreground max-w-2xl mx-auto mb-10 leading-relaxed">
          FancyFinance combines backend automation, secure credential storage,
          and real-time monitoring — all orchestrated through a Telegram bot you
          already know how to use.
        </p>

        <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
          <Button variant="hero" size="lg" asChild>
            <a href={TELEGRAM_URL} target="_blank" rel="noopener noreferrer">
              Start on Telegram
              <ArrowRight className="w-4 h-4 ml-1" />
            </a>
          </Button>
          <Button variant="heroOutline" size="lg" asChild>
            <a href="#how-it-works">How It Works</a>
          </Button>
        </div>
      </motion.div>
    </div>
  </section>
);

export default Hero;
