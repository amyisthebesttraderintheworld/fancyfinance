import Navbar from "@/components/landing/Navbar";
import Hero from "@/components/landing/Hero";
import WhatIs from "@/components/landing/WhatIs";
import HowItWorks from "@/components/landing/HowItWorks";
import Plans from "@/components/landing/Plans";
import Features from "@/components/landing/Features";
import Security from "@/components/landing/Security";
import Architecture from "@/components/landing/Architecture";
import SystemFlow from "@/components/landing/SystemFlow";
import FinalCTA from "@/components/landing/FinalCTA";
import Footer from "@/components/landing/Footer";

const Index = () => (
  <div className="min-h-screen">
    <Navbar />
    <Hero />
    <WhatIs />
    <HowItWorks />
    <Plans />
    <Features />
    <Security />
    <Architecture />
    <SystemFlow />
    <FinalCTA />
    <Footer />
  </div>
);

export default Index;
