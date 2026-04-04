import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  transpilePackages: ["@argonis/shared", "@argonis/db"],
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000",
  },
};

export default nextConfig;
