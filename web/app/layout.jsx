import "./globals.css";


export const metadata = {
  title: "Swarm Console",
  description: "3D playback and experiment review for the swarm coordination simulator.",
};


export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
