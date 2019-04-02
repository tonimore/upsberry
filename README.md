# Simple service for Raspberry with UPS18650 shield 
(https://github.com/linshuqin329/UPS-18650) to handle power events


* save voltage, battery capacity and current to log
* send email notifications 
* localized email messages 
* safe system shutdown when power lost and battery discharged 
* custom user functions for events 


## ups.py - main script. 
Usually could be placed in /usr/lib/ups/ups.py, but you can place it enywhere in the filesystem. 

Must be run via sudo, because of using GPIO library.

For install as System D service see ups.service file comments section.

Tested with Python 2.7.x. 

For security reasons be sure that only root has edit perrmissions: 
`sudo chown root:root /usr/lib/ups/ups.py; sudo chmod 755 /usr/lib/ups/ups.py`



## ups.conf - configurution
Hold overrided variables.

Must be saved in /etc/ups.conf

For security reasons be sure that only root has edit perrmissions:
`sudo chown root:root /etc/ups.conf; sudo chmod 755 /etc/ups.conf`




## Note:
To get PowerON status work you need make changes as described:
https://github.com/linshuqin329/UPS-18650/issues/4
