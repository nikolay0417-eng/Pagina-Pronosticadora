import argparse
import subprocess
import sys
import webbrowser
from pathlib import Path


def run(command):
    print(f"\n=== {' '.join(command)} ===")
    result = subprocess.run(command)
    if result.returncode != 0:
        raise SystemExit(f"Fallo el paso: {' '.join(command)}")


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Corre el flujo completo del agente deportivo: (opcional) actualizar datos, "
            "(opcional) calibrar el modelo, generar el panel visual y abrirlo en el navegador."
        )
    )
    parser.add_argument(
        "--actualizar-datos",
        action="store_true",
        help="Descarga datos nuevos con API-Football.py antes de generar el panel (puede tardar varios minutos).",
    )
    parser.add_argument(
        "--calibrar",
        action="store_true",
        help="Recalibra el modelo contra el historico antes de generar el panel (puede tardar varios minutos).",
    )
    parser.add_argument("--competition", default="LaLiga", help="Liga a usar si se pide --calibrar.")
    parser.add_argument("--limit", type=int, default=150, help="Partidos a usar si se pide --calibrar.")
    parser.add_argument("--sin-abrir", action="store_true", help="No abre el navegador al final.")
    return parser.parse_args()


def main():
    args = parse_args()
    python = sys.executable

    if args.actualizar_datos:
        run([python, "API-Football.py"])

    if args.calibrar:
        run(
            [
                python,
                "agente_pronosticos.py",
                "calibrate",
                "--competition",
                args.competition,
                "--limit",
                str(args.limit),
            ]
        )

    run([python, "dashboard.py"])

    dashboard_path = Path("dashboard.html").resolve()
    print(f"\nListo. Panel generado en {dashboard_path}")

    if not args.sin_abrir:
        webbrowser.open(dashboard_path.as_uri())


if __name__ == "__main__":
    main()
