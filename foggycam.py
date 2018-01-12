import urllib2 
import urllib
import json
from string import Template
from cookielib import CookieJar
import os
from collections import defaultdict
import traceback
from subprocess import Popen, PIPE
import uuid

class FoggyCam():
    nest_username=''
    nest_password=''

    nest_user_id=''
    nest_access_token=''
    nest_access_token_expiration=''
    nest_current_user=None

    nest_session_url='https://home.nest.com/session'
    nest_user_url='https://home.nest.com/api/0.1/user/#USERID#/app_launch'
    nest_api_login_url='https://webapi.camera.home.nest.com/api/v1/login.login_nest'
    nest_image_url='https://nexusapi-us1.camera.home.nest.com/get_image?uuid=#CAMERAID#&width=#WIDTH#&cachebuster=#CBUSTER#'

    nest_user_request_payload='{"known_bucket_types":["buckets","delayed_topaz","demand_charge","demand_charge_event","demand_response","device","device_alert_dialog","geofence_info","link","message","message_center","metadata","occupancy","quartz","safety","rate_plan","safety_summary","schedule","shared","structure","structure_history","structure_metadata","topaz","topaz_resource","tou","track","trip","tuneups","user","user_alert_dialog","user_settings","utility","where","widget_track"],"known_bucket_versions":[]}'

    nest_camera_array=[]
    nest_camera_buffer_threshold=200

    is_capturing=False
    cookie_jar=None
    merlin=None
    temp_dir_path=''
    local_path=''

    def __init__(self,username,password):
        self.nest_password = password
        self.nest_username = username
        self.cookie_jar = CookieJar()
        self.merlin = urllib2.build_opener(urllib2.HTTPCookieProcessor(self.cookie_jar))

        if not os.path.exists('_temp'):
            os.makedirs('_temp')
        
        self.local_path=os.path.dirname(os.path.abspath(__file__))
        self.temp_dir_path = os.path.join(self.local_path, '_temp')

    def initializeSession(self):
        print 'INFO: Initializing session...'

        payload = {'email':self.nest_username, 'password':self.nest_password}

        request = urllib2.Request(self.nest_session_url)
        request.add_header('Content-Type','application/json')

        response = self.merlin.open(request,json.dumps(payload))
        session_data = response.read()
        session_json = json.loads(session_data)

        self.nest_access_token = session_json['access_token']
        self.nest_access_token_expiration = session_json['expires_in']
        self.nest_user_id = session_json['userid']

        print 'INFO: [PARSED] Captured authentication token:'
        print self.nest_access_token

        print 'INFO: [PARSED] Captured expiration date for token:'
        print self.nest_access_token_expiration

        cookie_data = dict((cookie.name, cookie.value) for cookie in self.cookie_jar)
        for cookie in cookie_data:
            print cookie

        print 'INFO: [COOKIE] Captured authentication token:'
        print cookie_data["cztoken"]

        print 'INFO: Session initialization complete!'
    
    def login(self):
        print 'INFO: Performing user login...'

        post_data = {'access_token':self.nest_access_token}
        #post_data = json.dumps(post_data)
        post_data = urllib.urlencode(post_data)

        print "INFO: Auth post data"
        print post_data

        request = urllib2.Request(self.nest_api_login_url,data=post_data)
        request.add_header('Content-Type','application/x-www-form-urlencoded')

        response = self.merlin.open(request)
        session_data = response.read()
        
        print session_data

    def initializeUser(self):
        print 'INFO: Initializing current user...'

        user_url = self.nest_user_url.replace('#USERID#',self.nest_user_id)

        print 'INFO: Requesting user data from:'
        print user_url

        request = urllib2.Request(user_url)
        request.add_header('Content-Type','application/json')
        request.add_header('Authorization','Basic %s' % self.nest_access_token)

        response = self.merlin.open(request, self.nest_user_request_payload)

        response_data = response.read()

        print response_data

        user_object = json.loads(response_data)
        for bucket in user_object['updated_buckets']:
            bucket_id = bucket['object_key']
            if bucket_id.startswith('quartz.'):
                camera_id = bucket_id.replace('quartz.','')
                print 'INFO: Detected camera configuration.'
                print bucket
                print 'INFO: Camera UUID:'
                print camera_id
                self.nest_camera_array.append(camera_id)

    def captureImages(self,width=1280,produce_video=False,custom_path='',clear_images=False):
        print 'INFO: Capturing images...'

        self.is_capturing = True
        camera_buffer = defaultdict(list)

        while self.is_capturing:
            if not os.path.exists('capture'):
                os.makedirs('capture')

            for camera in self.nest_camera_array:
                file_id = str(uuid.uuid4().hex)

                camera_path = ''
                video_path = ''

                # Determine whether the entries should be copied to a custom path
                # or not.
                if not custom_path:
                    camera_path = os.path.join(self.local_path,'capture',camera,'images')
                    video_path = os.path.join(self.local_path,'capture',camera,'video')
                else:
                    camera_path = os.path.join(custom_path,'capture',camera,'images')
                    video_path = os.path.join(custom_path,'capture',camera,'video')

                # Provision the necessary folders for images and videos.
                if not os.path.exists(camera_path):
                    os.makedirs(camera_path)

                if not os.path.exists(video_path):
                    os.makedirs(video_path)

                image_url = self.nest_image_url.replace('#CAMERAID#', camera).replace('#CBUSTER#',str(file_id)).replace('#WIDTH#',str(width))
                print 'INFO: Current image URL:'
                print image_url

                request = urllib2.Request(image_url)
                request.add_header('accept','accept:image/webp,image/apng,image/*,*/*;q=0.8')
                request.add_header('accept-encoding','gzip, deflate, br')

                try:
                    response = self.merlin.open(request)

                    with open(camera_path + '/' + file_id + '.jpg', 'w') as f:
                        f.write(response.read())
                    
                    # Check if we need to compile a video
                    if produce_video:
                        camera_buffer_size = len(camera_buffer[camera])
                        print 'INFO: Camera buffer size for ' + camera
                        print camera_buffer_size

                        if camera_buffer_size < self.nest_camera_buffer_threshold:
                            print 'INFO: Registering bucket in buffer: ' + file_id
                            camera_buffer[camera].append(file_id)
                        else:
                            camera_image_folder = os.path.join(self.local_path,camera_path)

                            # Build the batch of files that need to be made into a video.
                            file_declaration = ''
                            for buffer_entry in camera_buffer[camera]:
                                file_declaration = file_declaration + 'file \'' + camera_image_folder + '/' + buffer_entry + '.jpg\'\n' 
                            concat_file_name = os.path.join(self.temp_dir_path, camera + '.txt')
                            with open(concat_file_name, 'w') as f:
                                f.write(file_declaration)

                            # Check if we have ffmpeg locally
                            ffmpegpath=os.path.join(self.local_path,'tools','ffmpeg')
                            if os.path.isfile(ffmpegpath):
                                print 'INFO: Found ffmpeg. Processing video!'
                                target_video_path = os.path.join(video_path, file_id + '.mp4')
                                process = Popen([ffmpegpath, '-r', '12', '-f', 'concat', '-safe', '0', '-i', concat_file_name, '-vcodec', 'libx264', '-crf', '25', '-pix_fmt', 'yuv420p', target_video_path], stdout=PIPE, stderr=PIPE)
                                process.communicate()
                                os.remove(concat_file_name)
                                print 'INFO: Video processing is complete!'

                                # If the user specified the need to remove images post-processing
                                # then clear the image folder from images in the buffer.
                                if clear_images:
                                    for buffer_entry in camera_buffer[camera]:
                                        deletion_target = os.path.join(camera_path, buffer_entry + '.jpg')
                                        print 'INFO: Deleting ' + deletion_target
                                        os.remove(deletion_target)
                            else:
                                print 'WARNING: No ffmpeg detected. Make sure the binary is in /tools.' 

                            # Empty buffer, since we no longer need the file records that we're planning
                            # to compile in a video.
                            camera_buffer[camera] = []       
                except Exception:
                    print 'ERROR: Could not download image from URL:'
                    print image_url

                    traceback.print_exc()

                    pass