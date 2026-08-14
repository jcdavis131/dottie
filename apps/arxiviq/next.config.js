/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'export',
  reactStrictMode: true,
  poweredByHeader: false,
  distDir: 'out',
  webpack: (config) => {
    config.resolve.fallback = { ...config.resolve.fallback, fs: false, path: false, os: false, child_process: false };
    config.externals = config.externals || [];
    return config;
  },
};
export default nextConfig;
