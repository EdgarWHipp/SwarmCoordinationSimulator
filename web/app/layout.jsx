import "./globals.css";


export const metadata = {
  title: "Consensus-Driven Drone Simulation",
  description: "Real-time distributed swarm coordination visualization powered by boids physics and decentralized consensus.",
};


export default function RootLayout({ children }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>{children}</body>
    </html>
  );
}
