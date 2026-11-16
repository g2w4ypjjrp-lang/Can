import { OctagonAlert, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { useAction } from "../api/hooks";
import { Confirm, ErrorBox } from "./ui";

export const RELEASE_PHRASE = "SERBEST BIRAK";

/** Üst çubukta her ekranda duran acil durdurma düğmesi. Kaldırmak onay ifadesi ister. */
export function KillSwitchControl({ engaged, onChange }: { engaged: boolean; onChange: () => Promise<unknown> | void }) {
  const [askEngage, setAskEngage] = useState(false);
  const [askRelease, setAskRelease] = useState(false);
  const engage = useAction((c) => c.post("/v1/kill-switch/engage", { reason: "Kullanıcı arayüzden durdurdu" }));
  const release = useAction((c) => c.post("/v1/kill-switch/release", { confirmation: RELEASE_PHRASE }));
  return (
    <>
      {engaged ? (
        <button type="button" className="kill-btn released" onClick={() => setAskRelease(true)} data-testid="kill-release">
          <ShieldCheck size={15} aria-hidden="true" /> Acil durdurmayı kaldır
        </button>
      ) : (
        <button type="button" className="kill-btn" onClick={() => setAskEngage(true)} data-testid="kill-engage">
          <OctagonAlert size={15} aria-hidden="true" /> ACİL DURDUR
        </button>
      )}
      {(release.error || engage.error) && (
        <div className="kill-error" role="alert">
          <ErrorBox error={release.error ?? engage.error} />
        </div>
      )}
      <Confirm
        open={askEngage}
        title="Acil durdurma"
        danger
        confirmLabel="Durdur"
        onCancel={() => setAskEngage(false)}
        onConfirm={async () => {
          setAskEngage(false);
          await engage.execute();
          await onChange();
        }}
      >
        Yeni işlem açılması hemen durdurulacak. Açık pozisyonların borsadaki stopları yerinde kalır. Devam edilsin mi?
      </Confirm>
      <Confirm
        open={askRelease}
        title="Acil durdurmayı kaldır"
        phrase={RELEASE_PHRASE}
        confirmLabel="Kaldır"
        onCancel={() => setAskRelease(false)}
        onConfirm={async () => {
          setAskRelease(false);
          await release.execute();
          await onChange();
        }}
      >
        Motor güvenlik koşulları sağlanınca yeniden işlem açabilir hâle gelir.
      </Confirm>
    </>
  );
}
