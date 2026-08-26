/** @type {import('next').NextConfig} */
const nextConfig = {
  // SSR enabled — dynamic thin UI + /api/pair/* live pairing queue
  reactStrictMode: true,
  poweredByHeader: false,
  images: { unoptimized: true },
  typescript: { ignoreBuildErrors: true },
  eslint: { ignoreDuringBuilds: true },
  webpack: (config) => {
    config.resolve.fallback = { ...config.resolve.fallback, fs: false, path: false, os: false, child_process: false };
    return config;
  },
};
export default nextConfig;
