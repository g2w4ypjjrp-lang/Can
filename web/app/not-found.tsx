import { SiteFooter } from "@/components/SiteFooter";
import { SiteHeader } from "@/components/SiteHeader";
import { Container, LinkButton } from "@/components/ui";

export default function NotFound() {
  return (
    <>
      <SiteHeader />
      <main id="icerik" className="flex-1">
        <Container className="py-24 text-center">
          <p className="text-sm font-semibold text-accent-text">404</p>
          <h1 className="mt-2 text-3xl font-bold tracking-tight text-fg">Sayfa bulunamadı</h1>
          <p className="mt-3 text-muted">Aradığınız sayfa taşınmış veya hiç var olmamış olabilir.</p>
          <div className="mt-8 flex justify-center">
            <LinkButton href="/">Ana sayfaya dön</LinkButton>
          </div>
        </Container>
      </main>
      <SiteFooter />
    </>
  );
}
