import os
import smtplib #to send email from one mail another
from email.message import EmailMessage #module used to create email template

SENDER_EMAIL = os.environ.get('MAIL_USERNAME', 'anushakottapalli2005@gmail.com')
SENDER_PASSWORD = os.environ.get('MAIL_PASSWORD', 'sjtw zbjv rdem nnqo')

def send_mail(to,subject,body):
    server=smtplib.SMTP_SSL('smtp.gmail.com',465)
    server.login(SENDER_EMAIL, SENDER_PASSWORD)
    msg=EmailMessage()
    msg['FROM']=SENDER_EMAIL
    msg['TO']=to
    msg['SUBJECT']=subject
    msg.set_content(body)
    server.send_message(msg)
    server.close()