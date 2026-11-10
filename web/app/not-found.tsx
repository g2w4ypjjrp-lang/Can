import { SiteFooter } from "@/components/SiteFooter";
import { SiteHeader } from "@/components/SiteHeader";
import { Backdrop, Container, LinkButton } from "@/components/ui";

export default function NotFound() {
  return (
    <>
      <SiteHeader />
      <main id="icerik" className="relative flex-1 overflow-hidden">
        <Backdrop />
        <Container className="relative py-28 text-center">
          <p aria-hidden="true" className="text-gradient text-8xl font-semibold tracking-tighter sm:text-9xl">
            404
          </p>
          <h1 className="mt-4 text-3xl font-semibold tracking-tight text-fg sm:text-4xl">Sayfa bulunamadı</h1>
          <p className="mx-auto mt-3 max-w-md text-muted">Aradığınız sayfa taşınmış veya hiç var olmamış olabilir.</p>
          <div className="mt-9 flex flex-wrap justify-center gap-3">
            <LinkButton href="/">Ana sayfaya dön</LinkButton>
            <LinkButton href="/sss" variant="secondary">
              Sık sorulan sorular
            </LinkButton>
          </div>
        </Container>
      </main>
      <SiteFooter />
    </>
  );
}
