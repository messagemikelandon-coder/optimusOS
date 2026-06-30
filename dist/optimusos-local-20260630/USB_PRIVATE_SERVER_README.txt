Optimus private server quick start
==================================

This USB contains a deployable Optimus folder for Ubuntu.

On Ubuntu:

1. Copy the folder from the USB to your home directory:

   cp -r /media/$USER/optimus/optimus-server ~/optimus

2. Start the server:

   cd ~/optimus
   bash start-optimus-ubuntu.sh

3. From another device on the same private network or VPN, open the URL printed by the script.
   It will look like:

   http://YOUR_UBUNTU_IP:8000

Notes:
- This is intended for local/private network use.
- Keep the USB and .env file private because they can contain service credentials.
- The Docker Compose file is adjusted by the script to allow other devices on your private network to connect.
