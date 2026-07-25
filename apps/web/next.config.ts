import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // The shared schema package ships TypeScript sources, not a build artifact.
  transpilePackages: ["@sentinel/shared-schemas"],
  typescript: {
    // Type errors must fail the build; they are never ignored.
    ignoreBuildErrors: false,
  },
};

export default nextConfig;
