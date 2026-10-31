import shutil
import os

src_dir = os.path.join("dist", "DonPolloPOS")
desktop_zip = os.path.expanduser(r"~\Desktop\DonPollo_POS_Portable.zip")

print(f"Empaquetando a {desktop_zip}...")
zip_target = os.path.join("dist", "DonPollo_POS_Portable")
shutil.make_archive(zip_target, "zip", src_dir)
shutil.copy2(f"{zip_target}.zip", desktop_zip)

print(f"Todo listo! Tamaño del zip: {round(os.path.getsize(desktop_zip) / (1024*1024), 2)} MB")
