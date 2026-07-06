import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  typescript: { ignoreBuildErrors: true },
  reactStrictMode: false,
  experimental: { workerThreads: false, cpus: 1 },
};

export default nextConfig;