/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // There is one implementation document. The finance pack used to have its
  // own implementation and design pages; both now live as one section of
  // /implementation, and the old URLs keep working.
  async redirects() {
    return [
      { source: "/finance/implementation", destination: "/implementation#the-finance-pack-atlas-for-one-vertical", permanent: true },
      { source: "/finance/design", destination: "/implementation#the-finance-pack-atlas-for-one-vertical", permanent: true },
    ];
  },
};

export default nextConfig;
