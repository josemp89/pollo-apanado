import shutil, os

# Sync gerencia.html to dist
dist_tpl = os.path.join("dist", "DonPolloPOS", "_internal", "app", "templates", "gerencia.html")
if os.path.exists(dist_tpl):
    shutil.copy2("app/templates/gerencia.html", dist_tpl)
    print("Updated gerencia.html in dist")

# Update zip on desktop
src_dir = os.path.join("dist", "DonPolloPOS")
desktop_zip = os.path.expanduser(r"~\Desktop\DonPollo_POS_Portable.zip")
zip_target = os.path.join("dist", "DonPollo_POS_Portable")
shutil.make_archive(zip_target, "zip", src_dir)
shutil.copy2(f"{zip_target}.zip", desktop_zip)
print("Updated desktop ZIP successfully!")
