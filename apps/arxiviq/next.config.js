/** @type {import('next').NextConfig} */
const nextConfig = {
  // output: 'export' removed for /conductor App Router dynamic thin UI — Vercel SSR allows real RPC snapshot <300ms
  reactStrictMode: true,
  poweredByHeader: false,
  webpack: (config) => {
    config.resolve.fallback = { ...config.resolve.fallback, fs: false, path: false, os: false, child_process: false };
    config.externals = config.externals || [];
    return config;
  },
};
export default nextConfig;
